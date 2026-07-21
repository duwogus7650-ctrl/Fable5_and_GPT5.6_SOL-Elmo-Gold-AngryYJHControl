"""MotorProfile 계약 테스트 (P1) — 완전 오프라인, 기존 코드 무접촉.

목 규율 (failure-ledger 2026-07-15 '목-실기 갭'): 드라이브-리드 목은 실기
확정치를 인코딩한다.
  * 현 유닛: CA[18]=65536, TS=100e-6 s, CL[1]=21.2132 A(=15 Arms*sqrt2),
    PL[1]=70.7107 A(피크, =50 Arms*sqrt2), CA[19]=21(실기확정),
    VH[2]=3,932,160 counts/s (= 3600 rpm * 65536 / 60).
  * 가상 2번째 모터: 극쌍 8, 저전류, 다른 counts/rev(4096) — 파생 rpm과
    NEED_DATA 분기 커버.
"""

from __future__ import annotations

import dataclasses
import json
import math
import os

import pytest

from motor_profile import (
    MotorProfile, list_profiles,
    FLAG_GREEN, FLAG_YELLOW, FLAG_DRIVE_ONLY, FLAG_USER_ONLY, FLAG_NEED_DATA,
    PP_DRIVE, PP_USER, PP_NEED_DATA,
)

# --- 실기 확정치 목 (현 유닛: Gold Twitter + 21극쌍 모터) --------------------
CURRENT_UNIT = {
    "CA[18]": 65536.0,        # counts/rev (실기확정)
    "TS": 100e-6,             # s (실기확정 100 µs)
    "CL[1]": 21.2132,         # A 진폭 (=15 Arms * sqrt2, 실기확정)
    "PL[1]": 70.7107,         # A 진폭 피크 (=50 Arms * sqrt2, 실기확정)
    "CA[19]": 21.0,           # 극쌍 (이 모터 실기확정)
    "CA[28]": 0.0,            # motor type raw
    "VH[2]": 3932160.0,       # counts/s -> 3600 rpm (3600/60*65536)
}

# --- 가상 2번째 모터 (극쌍 8 · 저전류 · counts/rev 4096) --------------------
VIRTUAL_8PP = {
    "CA[18]": 4096.0,
    "TS": 50e-6,
    "CL[1]": 2.5,
    "PL[1]": 7.07,
    "CA[28]": 1.0,
    "VH[2]": 204800.0,        # 204800*60/4096 = 3000 rpm 정확
    # CA[19] 의도적으로 부재 -> NEED_DATA 분기
}


# ===================================================================== 파생

def test_rated_rpm_drive_formula_current_unit():
    """VH[2]*60/CA[18]: 3932160*60/65536 = 3600 rpm 정확 (2경로 교차)."""
    p = MotorProfile.from_sources("unit21", CURRENT_UNIT)
    assert p.rated_rpm_drive == pytest.approx(3600.0, abs=1e-9)
    # 교차 검산 경로: rev/s * 60
    assert p.rated_rpm_drive == pytest.approx(
        (CURRENT_UNIT["VH[2]"] / CURRENT_UNIT["CA[18]"]) * 60.0)


def test_rated_rpm_drive_formula_virtual():
    p = MotorProfile.from_sources("virt8", VIRTUAL_8PP,
                                  {"pole_pairs": 8})
    assert p.rated_rpm_drive == pytest.approx(3000.0, abs=1e-9)


def test_drive_fields_captured_exactly():
    p = MotorProfile.from_sources("unit21", CURRENT_UNIT)
    assert p.counts_per_rev == 65536.0
    assert p.ts_s == pytest.approx(100e-6)
    assert p.cont_current_a == pytest.approx(21.2132)
    assert p.peak_current_a == pytest.approx(70.7107)
    assert p.motor_type == 0
    assert p.vh2_counts_per_s == 3932160.0
    # 물리 정합: 피크 > 연속, CL[1]/sqrt2 = 15 Arms
    assert p.peak_current_a > p.cont_current_a
    assert p.cont_current_a / math.sqrt(2.0) == pytest.approx(15.0, rel=1e-4)


# ============================================================ rated rpm 합성

def test_flag_green_when_sources_agree():
    p = MotorProfile.from_sources("unit21", CURRENT_UNIT,
                                  {"maxspeed": 3600.0})
    assert p.rated_rpm_flag == FLAG_GREEN
    assert p.effective_rated_rpm == pytest.approx(3600.0)


def test_flag_boundary_5pct():
    # 3450 vs 3600: dev = 150/3450 = 4.35 % <= 5 % -> GREEN
    p = MotorProfile.from_sources("unit21", CURRENT_UNIT,
                                  {"maxspeed": 3450.0})
    assert p.rated_rpm_flag == FLAG_GREEN
    assert p.effective_rated_rpm == pytest.approx(3450.0)  # min 채택
    # 3400 vs 3600: dev = 200/3400 = 5.88 % > 5 % -> YELLOW
    p2 = MotorProfile.from_sources("unit21", CURRENT_UNIT,
                                   {"maxspeed": 3400.0})
    assert p2.rated_rpm_flag == FLAG_YELLOW
    assert p2.effective_rated_rpm == pytest.approx(3400.0)


def test_effective_fail_closed_min_even_user_higher():
    """사용자가 드라이브보다 높게 적어도 effective = 드라이브(min)."""
    p = MotorProfile.from_sources("unit21", CURRENT_UNIT,
                                  {"maxspeed": 4000.0})
    assert p.effective_rated_rpm == pytest.approx(3600.0)
    assert p.rated_rpm_flag == FLAG_YELLOW   # 11 % 편차


def test_yellow_virtual_user_below_drive():
    p = MotorProfile.from_sources("virt8", VIRTUAL_8PP,
                                  {"maxspeed": 2500.0, "pole_pairs": 8})
    assert p.rated_rpm_drive == pytest.approx(3000.0)
    assert p.effective_rated_rpm == pytest.approx(2500.0)
    assert p.rated_rpm_flag == FLAG_YELLOW   # 20 % 편차


def test_drive_only_flag():
    p = MotorProfile.from_sources("unit21", CURRENT_UNIT)  # 사용자 입력 없음
    assert p.rated_rpm_user is None
    assert p.rated_rpm_flag == FLAG_DRIVE_ONLY
    assert p.effective_rated_rpm == pytest.approx(3600.0)


def test_user_only_flag():
    d = dict(CURRENT_UNIT)
    del d["VH[2]"]                                        # 드라이브 리드 불가
    p = MotorProfile.from_sources("unit21", d, {"maxspeed": 3600.0})
    assert p.rated_rpm_drive is None
    assert p.rated_rpm_flag == FLAG_USER_ONLY
    assert p.effective_rated_rpm == pytest.approx(3600.0)


def test_no_rpm_source_need_data_invalid():
    d = {"CA[18]": 65536.0, "CA[19]": 21.0}
    p = MotorProfile.from_sources("unit21", d)
    assert p.effective_rated_rpm is None
    assert p.rated_rpm_flag == FLAG_NEED_DATA
    assert not p.is_valid


# ================================================================== 극쌍

def test_pole_pairs_from_drive():
    p = MotorProfile.from_sources("unit21", CURRENT_UNIT)
    assert p.pole_pairs == 21
    assert p.pole_pairs_state == PP_DRIVE
    assert p.is_valid


def test_pole_pairs_unreadable_no_fallback_16():
    """CA[19] 부재 + 사용자 입력 없음 -> NEED_DATA, 16 폴백 절대 금지."""
    p = MotorProfile.from_sources("virt8", VIRTUAL_8PP)
    assert p.pole_pairs is None          # 16이 아님 — 폴백 트립와이어
    assert p.pole_pairs_state == PP_NEED_DATA
    assert not p.is_valid                # 입력 전엔 프로필 무효


def test_pole_pairs_garbage_is_need_data():
    for garbage in ("??", -3, 0, 21.5, float("nan")):
        d = dict(VIRTUAL_8PP, **{"CA[19]": garbage})
        p = MotorProfile.from_sources("virt8", d)
        assert p.pole_pairs_state == PP_NEED_DATA, garbage
        assert p.pole_pairs is None, garbage


def test_pole_pairs_user_supplied_resolves_need_data():
    p = MotorProfile.from_sources("virt8", VIRTUAL_8PP,
                                  {"pole_pairs": 8})
    assert p.pole_pairs == 8
    assert p.pole_pairs_state == PP_USER
    assert p.is_valid


def test_drive_ca19_wins_over_user():
    p = MotorProfile.from_sources("unit21", CURRENT_UNIT,
                                  {"pole_pairs": 8})
    assert p.pole_pairs == 21            # 드라이브 판독 가능 -> 드라이브 우선
    assert p.pole_pairs_state == PP_DRIVE


# ============================================================ 불변 · 이름

def test_frozen_immutable():
    p = MotorProfile.from_sources("unit21", CURRENT_UNIT)
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.pole_pairs = 16  # type: ignore[misc]


def test_empty_name_rejected():
    with pytest.raises(ValueError):
        MotorProfile.from_sources("", CURRENT_UNIT)
    with pytest.raises(ValueError):
        MotorProfile.from_sources("   ", CURRENT_UNIT)


# ============================================================ 직렬화 · 영속

def test_roundtrip_lossless_both_motors(tmp_path):
    snap = str(tmp_path)
    a = MotorProfile.from_sources("unit21", CURRENT_UNIT,
                                  {"maxspeed": 3600.0})
    b = MotorProfile.from_sources("virt8", VIRTUAL_8PP,
                                  {"maxspeed": 2500.0, "pole_pairs": 8})
    for p in (a, b):
        path = p.save(snap)
        assert os.path.isfile(path)
        q = MotorProfile.load(p.name, snap)
        assert q == p                          # 필드 전량 무손실
        assert q.to_dict() == p.to_dict()


def test_per_name_isolation_no_cross_contamination(tmp_path):
    """원장 A7: 모터별 개별 JSON — 서로의 이력/정격을 덮지 않는다."""
    snap = str(tmp_path)
    a = MotorProfile.from_sources("unit21", CURRENT_UNIT)
    b = MotorProfile.from_sources("virt8", VIRTUAL_8PP, {"pole_pairs": 8})
    pa, pb = a.save(snap), b.save(snap)
    assert pa != pb
    ra = MotorProfile.load("unit21", snap)
    rb = MotorProfile.load("virt8", snap)
    assert ra.pole_pairs == 21 and rb.pole_pairs == 8
    assert ra.counts_per_rev == 65536.0 and rb.counts_per_rev == 4096.0
    assert set(list_profiles(snap)) == {"unit21", "virt8"}


def test_history_slots_roundtrip(tmp_path):
    """P2+ 자리(ka_baseline·signature_band·i_ba_history) 왕복 무손실."""
    snap = str(tmp_path)
    p = MotorProfile.from_sources("unit21", CURRENT_UNIT)
    p2 = dataclasses.replace(
        p, ka_baseline=0.123456,
        signature_band={"i_ba_lo": 0.5, "i_ba_hi": 1.3},
        i_ba_history=(0.887, 0.95, 1.02))
    p2.save(snap)
    q = MotorProfile.load("unit21", snap)
    assert q == p2
    assert isinstance(q.i_ba_history, tuple)       # list로 열화 금지
    assert q.i_ba_history == (0.887, 0.95, 1.02)
    assert q.signature_band == {"i_ba_lo": 0.5, "i_ba_hi": 1.3}
    assert q.ka_baseline == pytest.approx(0.123456)


def test_need_data_and_flag_survive_roundtrip(tmp_path):
    """NEED_DATA/YELLOW 분기 상태가 저장 후에도 코드로 남는다."""
    snap = str(tmp_path)
    nd = MotorProfile.from_sources("virt8", VIRTUAL_8PP)          # NEED_DATA
    yl = MotorProfile.from_sources("unit21", CURRENT_UNIT,
                                   {"maxspeed": 3000.0})          # YELLOW
    nd.save(snap); yl.save(snap)
    assert MotorProfile.load("virt8", snap).pole_pairs_state == PP_NEED_DATA
    assert not MotorProfile.load("virt8", snap).is_valid
    assert MotorProfile.load("unit21", snap).rated_rpm_flag == FLAG_YELLOW


def test_load_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        MotorProfile.load("no_such_motor", str(tmp_path))


def test_json_payload_is_plain_and_keyed_by_name(tmp_path):
    snap = str(tmp_path)
    p = MotorProfile.from_sources("unit 21/gold", CURRENT_UNIT)
    path = p.save(snap)
    assert os.path.basename(path) == "unit_21_gold.json"   # slug된 개별 파일
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    assert raw["name"] == "unit 21/gold"
    assert raw["schema"] == 1
    assert raw["rated_rpm_drive"] == pytest.approx(3600.0)


# ============================== 학습상태 이월 (실기 결함 2026-07-22: 쓰기 전용)

_LIVE_IBA = 1.3297826865671643      # 실기 GREEN 런이 남긴 값
_LIVE_KA = 1792123.278946844


def _learned(name="m", readings=None):
    """GREEN 런을 한 번 통과한 프로필."""
    p = MotorProfile.from_sources(name, readings or CURRENT_UNIT)
    return p.with_green_run(i_ba_a=_LIVE_IBA, k_a=_LIVE_KA)


def test_with_learned_from_carries_only_the_learned_fields():
    """저장본이 주는 것은 ka_baseline/signature_band/i_ba_history **뿐**이다.
    드라이브 파생 필드는 살아있는 리드에서 와야 한다 — 같은 드라이브에 다른
    모터를 물렸을 때 이전 모터의 정격·전류한계가 되살아나면 안 된다."""
    saved = _learned()
    fresh = MotorProfile.from_sources("m", VIRTUAL_8PP)   # 다른 모터를 실측
    merged = fresh.with_learned_from(saved)

    for f in MotorProfile.LEARNED_FIELDS:
        assert getattr(merged, f) == getattr(saved, f), f
    for fld in dataclasses.fields(MotorProfile):
        if fld.name in MotorProfile.LEARNED_FIELDS:
            continue
        assert getattr(merged, fld.name) == getattr(fresh, fld.name), (
            "드라이브 파생 필드 %s 는 실측에서 와야 함" % fld.name)


def test_with_learned_from_none_is_identity():
    """모터와 첫 대면: 저장본이 없으면 이월할 것도 없다."""
    fresh = MotorProfile.from_sources("m", CURRENT_UNIT)
    assert fresh.with_learned_from(None) == fresh
    assert fresh.has_learned_state() is False


def test_learned_state_survives_a_save_load_cycle(tmp_path):
    """끊겨 있던 고리 자체: GREEN → save → (새 세션) load → 실측에 병합 →
    베이스라인이 다시 살아난다.  이게 안 돌아서 서명이 영원히 첫런 상한에
    묶였고 자기 측정을 검열했다."""
    saved = _learned()
    saved.save(str(tmp_path))

    reloaded = MotorProfile.load(saved.name, str(tmp_path))
    next_session = MotorProfile.from_sources(
        saved.name, CURRENT_UNIT).with_learned_from(reloaded)

    assert next_session.has_learned_state() is True
    assert next_session.ka_baseline == pytest.approx(_LIVE_KA)
    assert next_session.signature_band["i_ba_ref_a"] == pytest.approx(_LIVE_IBA)
    assert next_session.i_ba_history == saved.i_ba_history


def test_learned_state_is_not_shared_between_names(tmp_path):
    """격리 유지: 한 모터의 베이스라인이 다른 모터의 통전 봉투를 승인하면 안 된다."""
    _learned("motor-a").save(str(tmp_path))
    with pytest.raises(FileNotFoundError):
        MotorProfile.load("motor-b", str(tmp_path))


def test_has_learned_state_detects_each_slot():
    base = MotorProfile.from_sources("m", CURRENT_UNIT)
    assert base.has_learned_state() is False
    assert dataclasses.replace(base, ka_baseline=1.0).has_learned_state()
    assert dataclasses.replace(
        base, signature_band={"i_ba_ref_a": 1.0}).has_learned_state()
    assert dataclasses.replace(base, i_ba_history=(1.0,)).has_learned_state()
    # 기준값 없는 대역은 쓸 수 있는 상태가 아니다
    assert dataclasses.replace(
        base, signature_band={"alpha": 0.5}).has_learned_state() is False
