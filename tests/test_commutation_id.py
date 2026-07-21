# -*- coding: utf-8 -*-
"""P4 커뮤테이션 자립 ID 오프라인 시뮬 (SPEC docs/commutation-id-p4-spec.md §7).

CommutGearLashSim(GearLashSim) = 실기 의미론 목:
  1. delta_deg 상태.  UM=5 토크 = Kt·I·cos δ (방향 = sign(cos δ)); UM=3은 δ무관.
  2. MF=0x80: UM=5·MO=1·cos δ<0 → T_fault(0.3 s) 내 MF=128 래치 + MO/SO 드롭
     (idle에서 발생 — 램프 전).  이후 TC 쓰기는 err 58.
  3. CA[7] 쓰기: MO=1 거부·정수만.  쓰기 시 delta += s_sim·Δtick·(360/512)
     — s_sim은 생성자 파라미터(알고리즘 비공개).
  4. CS: UM=3·MO=1만 수용.  cs_survives=False면 UM=5 복귀 시 δ 원복.
  5. power_cycle(reroll): δ ~ {0,59,75,103,115}° 재추첨 + TW RAM 소실.
  6. 목-갭 3형제: PA/JV는 BG에서만 발효(베이스 VPSim), JV 프로파일러(베이스),
     wall-clock 직렬 지연 = command()마다 advance(serial_latency_s).
  7. 백래시·정지마찰·HOLD-CONFIRM = GearLashSim 상속 (lash 4500 cnt).

수용 시나리오 S1~S7 + 상태기계 골격/안전 단언.  하드웨어 무접촉.
"""
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import autotune_velpos as vp
import physics_gates
from autotune_velpos import GREEN, YELLOW, RED

import commutation_id as cid_mod
from commutation_id import (CommutationIDParams, CommutationIDResult,
                            run_commutation_id, wrap_ticks, delta_ticks)
from test_autotune_velpos import GearLashSim, VPSim, CL1


def _wrap180(d):
    return ((float(d) + 180.0) % 360.0) - 180.0


# 건강(δ=0) 상태에서 서명 램프가 래치하는 i_ba의 시뮬 기준값.  실기와 동일하게
# ref는 "같은 계기(램프+HOLD-CONFIRM)로 잰 건강 서명"이라 래치 양자화 바이어스가
# 분자/분모에서 상쇄된다 (스펙 §2① c_iba = i_ba_ref/i_ba_meas).
# CommutGearLashSim(i_s_load=0.5)의 건강 래치 실측치 — 캘리브레이션 런에서 확정.
IBA_REF = 0.524     # δ=0 캘리브레이션 런 실측 0.5239 A (아래 앵커 테스트가 감시)
I_S_LOAD = 0.5      # 시뮬 부하 정지마찰 [A]: 대역 하한(0.02·CL=0.42 A) 위 +
                    # δ≈75°까지 1.30 A 캡 안에서 측정 가능하도록 선정


# ======================================================================================
# CommutGearLashSim — 목=실기 의미론 (스펙 §7 1~7)
# ======================================================================================
class CommutGearLashSim(GearLashSim):
    T_FAULT_S = 0.3

    def __init__(self, delta0_deg=0.0, s_sim=+1, cs_survives=True,
                 mf_noncommut=False, serial_latency_s=0.0015,
                 i_s_load=I_S_LOAD, lash_cnt=4500.0, **kw):
        kw.setdefault("vel_noise", 0.0)
        GearLashSim.__init__(self, lash_cnt=lash_cnt, i_s_load=i_s_load, **kw)
        self.regs["CA[19]"] = 16          # 벤치 모터 = 극쌍 16 (사용자 확정)
        self.delta_deg = float(delta0_deg)
        self.s_sim = int(s_sim)           # 비공개 — 알고리즘이 읽으면 반칙
        self.cs_survives = bool(cs_survives)
        self.mf_noncommut = bool(mf_noncommut)
        self.serial_latency_s = float(serial_latency_s)
        self._fault_t = 0.0
        self._k_a_free0 = self.k_a_free
        self._wiring_sign = self.commut_sign
        self._cs_session = False
        self._delta_pre_cs = None
        self.tw_ram = {}
        self.tc_um5_max = 0.0
        self.tc_um3_max = 0.0
        self.enable_count = 0

    # ---- 물리: UM=5 토크 = cos δ 배 (엔게이지/프리플라이트 양쪽) ----------------
    def _step(self, nk):
        eff = (math.cos(math.radians(self.delta_deg))
               if self.regs.get("UM") == 5 else 1.0)
        # MF=0x80 모델 (Admin p85 speed tracking): UM5·MO1·cosδ<0 홀드 양귀환
        # → T_fault 내 폴트 래치 + SO/MO 드롭.  idle에서 발생 (지령 불요).
        if (self.regs["MO"] == 1 and self.regs.get("UM") == 5
                and (eff < 0.0 or self.mf_noncommut)):
            self._fault_t += self.dt
            if self._fault_t >= self.T_FAULT_S and self.regs["MF"] == 0:
                self.regs["MF"] = 128
                self.regs["MO"] = 0        # SO는 MO에서 파생 (base _query)
        else:
            self._fault_t = 0.0
        if self.regs.get("UM") == 3:
            # UM=3 스테퍼 = 위치 홀드: TC는 자유 토크로 적분되지 않는다.
            # 회전은 _apply_pa(BG 발효)의 필드-추종 텔레포트로만 — 베이스
            # VPSim은 UM 구분 없이 TC를 적분하므로(기존 스위트에선 정지마찰이
            # 드래그 전류보다 커서 잠복) 여기서 토크 경로를 끊는다.
            self.um5_eff = 0.0
            self.k_a_free = 0.0
        else:
            self.um5_eff = abs(eff)        # 엔게이지 경로 (base VPSim._step)
            self.k_a_free = self._k_a_free0 * abs(eff)   # 프리플라이트 경로
        self.commut_sign = self._wiring_sign * (1.0 if eff >= 0 else -1.0)
        try:
            GearLashSim._step(self, nk)
        finally:
            self.k_a_free = self._k_a_free0

    # ---- 전송: 직렬 왕복 wall-clock 지연 (목-갭 #3) ------------------------------
    def command(self, cmd, timeout_ms=1000, allow_motion=False):
        if self.serial_latency_s > 0:
            self.advance(self.serial_latency_s)
        return VPSim.command(self, cmd, timeout_ms=timeout_ms,
                             allow_motion=allow_motion)

    # ---- 레지스터 의미론 ---------------------------------------------------------
    def _write(self, name, v):
        regs = self.regs
        if name == "MO":
            if v == 0:
                regs["MF"] = 0             # disable = 폴트 래치 해제 (시뮬 가정)
            else:
                self.enable_count += 1
            self._fault_t = 0.0
            return VPSim._write(self, name, v)
        if name == "TC":
            if regs["MO"] != 1:
                raise IOError("err 58: Servo must be on")
            if regs.get("UM") == 5:
                self.tc_um5_max = max(self.tc_um5_max, abs(float(v)))
            else:
                self.tc_um3_max = max(self.tc_um3_max, abs(float(v)))
            return VPSim._write(self, name, v)
        if name == "CA[7]":
            if regs["MO"] == 1:
                raise IOError("CA[7] write requires MO=0 (commutation reset)")
            f = float(v)
            if f != int(f):
                raise IOError("err 162: BAD_NUMBER — CA[7] integer only")
            old = float(regs.get("CA[7]", 0.0))
            dt_ticks = ((int(f) - old + 512.0) % 1024.0) - 512.0
            self.delta_deg = _wrap180(
                self.delta_deg + self.s_sim * dt_ticks * (360.0 / 512.0))
            regs["CA[7]"] = int(f)
            return ""
        if name == "CS":
            if regs.get("UM") != 3:
                raise IOError("CS accepted in UM=3 only")
            if regs["MO"] != 1:
                raise IOError("CS requires MO=1 (rotor held)")
            self._delta_pre_cs = self.delta_deg
            i_hold = abs(self.tc)
            if i_hold > self.i_s_load:
                # 단방향 당김 정렬 후 CS: 잔차 = asin(I_fric/I_align) (스펙 §5)
                self.delta_deg = math.degrees(
                    math.asin(min(1.0, self.i_s_load / i_hold)))
            self._cs_session = True
            return ""
        if name == "UM":
            out = VPSim._write(self, name, v)   # MO=1이면 base가 거부
            if (int(v) == 5 and self._cs_session and not self.cs_survives
                    and self._delta_pre_cs is not None):
                self.delta_deg = self._delta_pre_cs   # CS 미생존 → δ 원복
                self._cs_session = False
            return out
        return VPSim._write(self, name, v)

    # ---- 전원 사이클 (스펙 §7 5) -------------------------------------------------
    def power_cycle(self, reroll=False, pool=(0.0, 59.0, 75.0, 103.0, 115.0)):
        self.regs["MO"] = 0
        self.regs["MF"] = 0
        self.regs["PA"] = 0.0
        self.tc = 0.0
        self.i_act = 0.0
        self.cmd_prev = 0.0
        self.v = 0.0
        self.v_meas = 0.0
        self.integ = 0.0
        self.mode = "tc"
        self.jv = 0.0
        self.jv_target = 0.0
        self.jv_pending = None
        self.pa_pending = None
        self.tw_ram = {}                   # TW = 전원 리셋 휘발 (CR)
        self._cs_session = False
        self._delta_pre_cs = None
        self._fault_t = 0.0
        if reroll:
            self.delta_deg = float(self.rng.choice(list(pool)))


# ======================================================================================
# helpers
# ======================================================================================
def _cid_params(drive, tmpdir, **kw):
    kw.setdefault("sleep_fn", drive.advance)
    kw.setdefault("clock_fn", lambda: drive.t)
    kw.setdefault("i_ba_ref_a", IBA_REF)
    return CommutationIDParams(snapshot_dir=str(tmpdir), **kw)


def _cmds(drive):
    return [c.replace(" ", "").upper() for c, _allow in drive.log]


def _assert_safe_close(drive, ca7_expected):
    """계약 단언: abort/종결 후 스냅숏 원복 (UM5·MO0·TC0·리밋·CA[7]) +
    서명 통전 ≤ 1.30 A + UM3 ≤ 6.0 A + SV 절대 무전송."""
    assert drive.regs["MO"] == 0
    assert drive.regs["MF"] == 0
    assert drive.regs["UM"] == 5
    assert abs(drive.tc) <= 1e-9
    assert drive.regs["SD"] == pytest.approx(1e6)        # 리밋 원복
    assert drive.regs["ER[2]"] == pytest.approx(1e8)
    assert drive.regs["HL[2]"] == 0
    assert drive.regs["LL[2]"] == 0
    assert drive.regs["CA[7]"] == ca7_expected
    assert drive.tc_um5_max <= vp.SIGNATURE_ENERGIZE_ABS_MAX_A + 1e-9, \
        "서명(UM5) 통전이 안전천장 초과: %.3f A" % drive.tc_um5_max
    assert drive.tc_um3_max <= 6.0 + 1e-9, \
        "UM3 통전이 승인 전용 한계 미만이어야 함: %.3f A" % drive.tc_um3_max
    cmds = _cmds(drive)
    assert not any(c == "SV" or c.startswith("SV=") for c in cmds), \
        "SV는 오퍼레이터 전용 — 자동 전송 금지"


def _corrections(res):
    return [i for i in res.evidence["iterations"] if i.get("event") == "correct"]


# ======================================================================================
# 골격/단위 (스펙 §3 수치 오라클)
# ======================================================================================
def test_wrap_and_delta_tick_spec_oracle():
    # 스펙 §3 예: δ̂=103° → Δ=146; CA[7]=438,s=+1 → wrap(292); 플립 = wrap(438+256)=−330
    assert delta_ticks(103.0) == 146
    assert wrap_ticks(438 - 146) == 292
    assert wrap_ticks(438 + 256) == -330
    assert wrap_ticks(-458) == -458            # 유효 범위 내 항등
    assert wrap_ticks(600) == -424
    assert cid_mod.DEG_PER_TICK == pytest.approx(0.703125)


def test_cap_above_ceiling_rejected_before_any_write(tmp_path):
    drive = CommutGearLashSim()
    res = run_commutation_id(
        drive, _cid_params(drive, tmp_path, signature_cap_a=1.31))
    assert res.status == RED
    assert "안전천장" in res.reason or "cap" in res.reason
    assert drive.enable_count == 0
    assert not any("=" in c for c in _cmds(drive)), "쓰기 전 거부여야 함"


def test_candidate_c_sealed(tmp_path):
    drive = CommutGearLashSim()
    res = run_commutation_id(
        drive, _cid_params(drive, tmp_path, allow_candidate_c=True))
    assert res.status == RED
    assert "봉인" in res.reason
    assert drive.enable_count == 0


def test_um3_ladder_operator_only_current_rejected(tmp_path):
    drive = CommutGearLashSim()
    res = run_commutation_id(
        drive, _cid_params(drive, tmp_path,
                           um3_align_i_ladder=(2.0, 4.24, 8.49)))
    assert res.status == RED
    assert "오퍼레이터" in res.reason
    assert drive.enable_count == 0


def test_healthy_delta0_green_without_correction(tmp_path):
    """골격 기준런: δ0=0 — 보정 0회, 플립 0회, GREEN.  IBA_REF 캘리브레이션의
    앵커이기도 하다 (측정 i_ba가 ref의 ±15% 안이어야 한다)."""
    drive = CommutGearLashSim(delta0_deg=0.0)
    res = run_commutation_id(drive, _cid_params(drive, tmp_path))
    assert res.status == GREEN, (res.status, res.reason, res.warnings)
    assert res.path_used == "A"
    assert res.evidence["a_iters"] == 0
    assert res.evidence["flips"] == 0
    meas = [i for i in res.evidence["iterations"] if i["event"] == "measure"]
    assert meas and meas[0]["detected"]
    assert abs(meas[0]["i_ba_a"] / IBA_REF - 1.0) <= 0.15
    _assert_safe_close(drive, ca7_expected=438)   # 보정 없음 → 원값 유지
    assert res.evidence["final_state"]["pass"] is True
    assert res.evidence["expect_slip_verdict"]["status"] != RED


# ======================================================================================
# S1 — δ0=59°, s_sim=+1: 플립 없이 A 1회 → GREEN, |δ|≤25.8°
# ======================================================================================
def test_s1_delta59_one_iteration_green(tmp_path):
    drive = CommutGearLashSim(delta0_deg=59.0, s_sim=+1)
    res = run_commutation_id(drive, _cid_params(drive, tmp_path))
    assert res.status == GREEN, (res.status, res.reason, res.warnings)
    assert res.path_used == "A"
    assert res.evidence["flips"] == 0
    assert res.evidence["a_iters"] == 1                  # A 1회
    assert res.evidence["enables"]["a_path"] <= 4
    assert abs(_wrap180(drive.delta_deg)) <= 25.8        # 실제 δ 수렴
    assert abs(res.delta_est_deg) <= 25.8
    assert res.ca7_sign_resolved == +1                   # 개선으로 s=+1 확정
    corr = _corrections(res)
    assert len(corr) == 1
    assert 50.0 <= corr[0]["delta_est_deg"] <= 70.0      # δ̂ ≈ 59°
    _assert_safe_close(drive, ca7_expected=res.ca7_after)
    assert res.ca7_after == corr[0]["ca7"]               # GREEN은 보정값 유지


# ======================================================================================
# S2 — δ0=103°: FAULT→플립1→보정→GREEN, path='A+flip', enable≤4
# ======================================================================================
def test_s2_delta103_flip_then_corrected_green(tmp_path):
    drive = CommutGearLashSim(delta0_deg=103.0, s_sim=+1)
    res = run_commutation_id(drive, _cid_params(drive, tmp_path))
    assert res.status == GREEN, (res.status, res.reason, res.warnings)
    assert res.path_used == "A+flip"
    assert res.evidence["flips"] == 1
    assert res.evidence["enables"]["a_path"] <= 4        # 총 enable ≤ 4
    assert abs(_wrap180(drive.delta_deg)) <= 25.8
    watches = res.evidence["enable_watch"]
    assert watches[0]["verdict"] == "FAULT_0x80"         # idle 폴트 (램프 전)
    assert watches[0]["mf"] == 0x80
    _assert_safe_close(drive, ca7_expected=res.ca7_after)


# ======================================================================================
# S3 — δ0=75°, ca7_sign=None, s_sim=−1: 1스텝이 s=−1 확정 후 GREEN
# ======================================================================================
def test_s3_sign_step_resolves_minus_one(tmp_path):
    drive = CommutGearLashSim(delta0_deg=75.0, s_sim=-1)
    res = run_commutation_id(drive, _cid_params(drive, tmp_path,
                                                ca7_sign=None))
    assert res.status == GREEN, (res.status, res.reason, res.warnings)
    assert res.ca7_sign_resolved == -1
    assert res.evidence["flips"] == 0                    # 플립 아닌 부호쌍 해소
    pairs = [i for i in res.evidence["iterations"]
             if i.get("event") == "sign_pair"]
    assert len(pairs) == 1 and pairs[0]["h_second"] == -1
    assert abs(_wrap180(drive.delta_deg)) <= 25.8
    assert res.evidence["enables"]["a_path"] <= 4
    _assert_safe_close(drive, ca7_expected=res.ca7_after)


# ======================================================================================
# S4 — δ0=103°, cs_survives=False, A봉쇄(max_a_iters=0): B 시도 → 복귀상실 검출
# ======================================================================================
def test_s4_cs_not_surviving_um5_detected_honest_red(tmp_path):
    drive = CommutGearLashSim(delta0_deg=103.0, cs_survives=False)
    res = run_commutation_id(
        drive, _cid_params(drive, tmp_path, max_a_iters=0))
    assert res.status in (YELLOW, RED)
    assert res.status == RED                              # 확립 실패 = 정직 RED
    assert "CS" in res.reason and "생존" in res.reason
    bev = res.evidence["candidate_b"]
    assert bev["established"] is False
    assert len(bev["rungs"]) == 3                         # 사다리 3단 전부 시도
    for rung in bev["rungs"]:
        assert "미생존" in rung["verdict"] or "불합격" in rung["verdict"]
    assert drive.delta_deg == pytest.approx(103.0, abs=1.0)  # δ 원복 관측
    _assert_safe_close(drive, ca7_expected=438)           # CA[7] 원본복원
    assert res.path_used == "B"


# ======================================================================================
# S5 — reroll: A GREEN 후 power_cycle → 부트 B확립 → 서명 GREEN → YELLOW '세션한정'
# ======================================================================================
def test_s5_power_reroll_then_b_session_scoped_yellow(tmp_path):
    drive = CommutGearLashSim(delta0_deg=59.0, s_sim=+1)
    res1 = run_commutation_id(drive, _cid_params(drive, tmp_path / "run1"))
    assert res1.status == GREEN, (res1.status, res1.reason)
    ca7_fixed = res1.ca7_after
    assert drive.regs["CA[7]"] == ca7_fixed

    drive.tw_ram["TW[18]"] = 1                            # 세션 RAM 센티널
    drive.power_cycle(reroll=True, pool=(103.0,))         # δ 재추첨 (결정적)
    assert drive.delta_deg == pytest.approx(103.0)
    assert drive.tw_ram == {}                             # TW RAM 소실

    # 매전원 부트 표준(스펙 §5 승격 경로): A 보정 없이 B 확립 + 서명
    res2 = run_commutation_id(
        drive, _cid_params(drive, tmp_path / "run2", max_a_iters=0))
    assert res2.status == YELLOW, (res2.status, res2.reason, res2.warnings)
    assert "세션한정" in res2.reason and "CS" in res2.reason
    assert res2.path_used == "B"
    bev = res2.evidence["candidate_b"]
    assert bev["established"] is True
    assert bev["rungs"][0]["signature"]["pass"] is True   # 첫 단에서 확립
    assert abs(_wrap180(drive.delta_deg)) <= 25.8         # CS가 세션 δ 유지
    _assert_safe_close(drive, ca7_expected=ca7_fixed)     # CA[7]은 원본(=run1값)
    assert res2.evidence["final_state"]["pass"] is True


# ======================================================================================
# S6 — δ무관 MF=128 주입: 플립 2회 FAULT → UM3 판별 → RED "비-커뮤", CA[7] 원복
# ======================================================================================
def test_s6_noncommutation_fault_routed_red_ca7_restored(tmp_path):
    drive = CommutGearLashSim(delta0_deg=0.0, mf_noncommut=True)
    res = run_commutation_id(drive, _cid_params(drive, tmp_path))
    assert res.status == RED
    assert "비-커뮤" in res.reason
    watches = res.evidence["enable_watch"]
    a_watches = [w for w in watches if w.get("verdict") == "FAULT_0x80"]
    assert len(a_watches) >= 2                            # 플립 양측 폴트
    assert res.evidence["flips"] == 1
    drag = res.evidence.get("um3_drag")
    assert drag is not None and drag.get("pa_effective", True)
    assert drag["follow_ratio"] >= 0.9                    # UM3 구동 정상 증거
    assert "정상" in res.reason                            # → 비-커뮤 판별문
    _assert_safe_close(drive, ca7_expected=438)           # CA[7] 원복
    assert res.evidence["ca7_restore"]["pass"] is True


# ======================================================================================
# S7 — max_a_iters 소진: 3회째 보정 없음, CA[7] 원복, 정직 RED
# ======================================================================================
def test_s7_iteration_cap_exhausted_honest_red(tmp_path):
    # 정지마찰 2.5 A(GearLashSim 기본) ≫ 1.30 A 캡 → 매 측정 BRACKET → 수렴 불가
    drive = CommutGearLashSim(delta0_deg=59.0, i_s_load=2.5)
    res = run_commutation_id(
        drive, _cid_params(drive, tmp_path, allow_candidate_b=False))
    assert res.status == RED
    assert "max_a_iters" in res.reason and "3회째" in res.reason
    assert res.evidence["a_iters"] == 2
    assert len(_corrections(res)) == 2                    # 3회째 없음
    assert res.evidence["enables"]["a_path"] <= 4
    meas = [i for i in res.evidence["iterations"] if i["event"] == "measure"]
    assert meas and all(m["quality"] == "BRACKET" for m in meas)
    assert "candidate_b" not in res.evidence              # B 비활성 존중
    _assert_safe_close(drive, ca7_expected=438)           # CA[7] 원복
    assert res.evidence["final_state"]["pass"] is True


# ======================================================================================
# 회귀 이빨 — 시뮬 자체가 실기 의미론을 강제하는지 (목-갭 3형제)
# ======================================================================================
def test_sim_ca7_write_rejected_while_enabled():
    drive = CommutGearLashSim()
    drive.regs["MO"] = 1
    with pytest.raises(IOError):
        drive._write("CA[7]", 300)
    drive.regs["MO"] = 0
    with pytest.raises(IOError):
        drive._write("CA[7]", 300.5)                      # 정수만


def test_sim_cs_requires_um3():
    drive = CommutGearLashSim()
    drive.regs["MO"] = 1
    with pytest.raises(IOError):
        drive._write("CS", 0.0)                           # UM=5에서 거부


def test_sim_idle_fault_fires_only_when_cos_negative():
    drive = CommutGearLashSim(delta0_deg=103.0, serial_latency_s=0.0)
    drive.regs["MO"] = 1
    drive.advance(0.5)
    assert drive.regs["MF"] == 128 and drive.regs["MO"] == 0   # 래치+드롭
    drive.power_cycle()
    drive.delta_deg = 20.0
    drive.regs["MO"] = 1
    drive.advance(2.0)
    assert drive.regs["MF"] == 0 and drive.regs["MO"] == 1     # 안정 반평면


def test_sim_serial_latency_advances_wall_clock():
    drive = CommutGearLashSim()
    t0 = drive.t
    drive.command("MF")
    assert drive.t > t0                                   # 직렬 왕복 = 실시간


# ======================================================================================
# 부트스트랩 — 베이스라인 없는 첫 런: 플립까지 수행하고 정직한 YELLOW로 종료
# (실기 2026-07-21: CA[7]=322에서 enable마다 MF=128 재현.  기준은 서명 GREEN에서
#  생기고 서명은 커뮤가 나쁘면 못 도는 순환을, 플립 경로 해제로 끊는다.)
# ======================================================================================
def test_no_baseline_bad_commutation_flips_and_yellow_keeps_flip(tmp_path):
    """기준 없음 + cos δ<0: PreflightError로 거부하지 말고 180° 플립을 적용한 뒤
    그 CA[7]을 유지한 채 YELLOW로 종료해야 한다 (다음 서명이 베이스라인을 심는다)."""
    drive = CommutGearLashSim(delta0_deg=103.0, s_sim=+1)
    ca7_before = drive.regs["CA[7]"]

    res = run_commutation_id(drive, _cid_params(drive, tmp_path,
                                                i_ba_ref_a=None))

    assert res.status == YELLOW, (res.status, res.reason, res.warnings)
    assert res.evidence["flips"] == 1
    assert res.path_used == "A+flip"
    # 첫 enable이 idle에서 MF=0x80 → 플립의 트리거
    assert res.evidence["enable_watch"][0]["verdict"] == "FAULT_0x80"
    # 플립은 유지된다 (원복 금지) — 인에이블이 안정화된 상태가 산출물
    assert res.ca7_after != ca7_before
    assert drive.regs["CA[7]"] == res.ca7_after
    assert "플립" in res.reason and "베이스라인" in res.reason
    _assert_safe_close(drive, ca7_expected=res.ca7_after)


def test_no_baseline_healthy_commutation_yellow_without_touching_ca7(tmp_path):
    """기준 없음 + 커뮤 건강(폴트 없음): 플립도 보정도 하지 않고, δ 정량 불가를
    정직하게 YELLOW로 보고한다 (CA[7] 무변경)."""
    drive = CommutGearLashSim(delta0_deg=0.0)
    ca7_before = drive.regs["CA[7]"]

    res = run_commutation_id(drive, _cid_params(drive, tmp_path,
                                                i_ba_ref_a=None))

    assert res.status == YELLOW, (res.status, res.reason, res.warnings)
    assert res.evidence["flips"] == 0
    assert res.ca7_after == ca7_before
    assert drive.regs["CA[7]"] == ca7_before
    assert "기준 없음" in res.reason
    _assert_safe_close(drive, ca7_expected=ca7_before)
