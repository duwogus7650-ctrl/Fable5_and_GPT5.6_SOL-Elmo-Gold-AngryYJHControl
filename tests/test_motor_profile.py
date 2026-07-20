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
