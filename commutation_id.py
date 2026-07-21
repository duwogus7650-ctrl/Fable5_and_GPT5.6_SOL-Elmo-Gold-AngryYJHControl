# -*- coding: utf-8 -*-
"""P4 — 백래시 내성 커뮤테이션 자립 ID (SPEC docs/commutation-id-p4-spec.md §4).

전원 재인가 후 EAS 없이 앱 단독으로 커뮤테이션을 확립한다.  상태기계
S0 SNAPSHOT → S1 ENABLE-WATCH → S2 FLIP → S3 MEASURE → S4 CORRECT → S5 CAP →
S6 CLOSE.  물리 모델(스펙 §0/§1):

  * δ = 드라이브 가정 전기각 − 실제 전기각.  UM=5 토크/암페어 = cos δ배.
  * cos δ < 0 이면 MO=1 idle 홀드가 양귀환 → MF=0x80(speed tracking) 셧.
  * cos δ 와 cos(δ−180°)는 동시에 음이 될 수 없다 → CA[7] 256tick(=180°)
    플립 한 번이면 반드시 안정 반평면 (S2).  두 번 다 폴트면 δ 원인이 아님.
  * CA[7]: 정수 −512..512, 1 tick = 0.703125° elec (CA[18]=65536, 전기
    1회전 = 4096 cnt, p=16 기준 스펙 동결).

재사용 (autotune_velpos — 로직 무변경, import/호출만):
  _Ctx/_cmd/_write/_sleep/_emit/_seg, _wait_rest, _do_abort(+리밋 복원),
  _breakaway_ramp(HOLD-CONFIRM 서명 램프, signature_only 모드),
  _um3_drag(커뮤 무관 토크 오라클), _apply_limits_verified,
  _capture_signature_final_state, SIGNATURE_ENERGIZE_ABS_MAX_A(=1.30 A 천장).
physics_gates 소비: sig_band(수렴 판정) · sig_first_run(expect-slip 판정) ·
  derive_drag_current(I_test=i_ba/√2) · (ka_drop는 K_a 측정 공급 시).

부호 해소(스펙 §3): 측정은 |δ̂|만 준다.  첫 보정은 s=+1 가설로 적용하고
1스텝 반증으로 확정한다 — 재측정 |δ̂| 감소 = 가설 확정, 증가 또는 재-enable
폴트(=|δ|가 90°를 넘음) = 가설 기각 → 원복 후 반대 부호 적용.  이 한 쌍은
서로 다른 가설이므로 max_a_iters 캡에 셈하지 않는다(총 enable ≤ 4는 불변).
주의: 이 절차가 확정하는 것은 s·sign(δ)의 곱이다 — 장치 상수 CA7_SIGN의
최종 동결은 내일 실기 R3(δ 부호를 아는 조건)에서 한다.

안전 계약: 서명(UM=5) 통전 ≤ SIGNATURE_ENERGIZE_ABS_MAX_A=1.30 A (명시
초과 요청은 거부).  UM=3 사다리 ≤ 6.0 A (8.49 A는 오퍼레이터 승인 전용 —
본 모듈에서 금지).  UM3 시퀀스당 통전 ≤ 20 s + 시퀀스 간 휴지 ≥ 통전.
모든 종료 경로에서 _do_abort(TC=0→MO=0→UM→리밋 복원) + CA[7] 원복
(GREEN A-경로만 보정값 유지; SV는 절대 보내지 않는다 — 오퍼레이터 전용).

순수 오프라인 실행 전제: 실기 접속은 내일 감독 런북 R0~R6에서만.
"""
from __future__ import annotations

import copy
import json
import math
import os
import re
import time
from dataclasses import dataclass, field, replace as _dc_replace
from types import SimpleNamespace
from typing import Callable, Optional, Sequence

import autotune_velpos as vp
import physics_gates
from autotune_velpos import GREEN, YELLOW, RED

__all__ = [
    "CommutationIDParams", "CommutationIDResult", "run_commutation_id",
    "wrap_ticks", "delta_ticks",
]

# ---- frozen geometry / thresholds (스펙 §0/§2/§4 — 신규 매직넘버 없음) --------
TICKS_PER_EREV = 512                  # CA[7]/PA 스테퍼 단위 (CR)
DEG_PER_TICK = 360.0 / TICKS_PER_EREV  # 0.703125° elec/tick
CA7_RANGE = (-512, 512)
FLIP_TICKS_DEFAULT = 256              # 180° elec — §1.1 플립 프리앰블
DELTA_GREEN_DEG = 25.8                # = K_a비 0.90 경계 (스펙 §2 표)
BRACKET_DELTA_DEG = 90.0              # cap 무이탈 → |δ|∈[60,120]° 상계 → 90°
A_ENABLE_BUDGET = 4                   # 총 enable ≤ 4 (스펙 S5)
ENABLE_WATCH_POLL_S = 0.05            # MF 폴 주기 (스펙 S1: 50 ms)
SO_TIMEOUT_S = 2.0
MF_SPEED_TRACKING = 0x80
IMPROVE_FRAC = 0.7                    # 재측정 |δ̂| < 0.7×이전 → 가설 확정
B_ANCHOR_PA_TICKS = 384               # CR p62 앵커쌍 PA=384 / CS=0
B_PA_STEP_TICKS = 32                  # 스텝 ≤ 반전기피치(256tick)의 1/8
B_TC_RAMP_STEPS = 10                  # 준정적 정렬 램프
B_TC_RAMP_STEP_S = 0.05
UM3_LADDER_MAX_A = 6.0                # 8.49 A(0.4·CL)는 오퍼레이터 승인 전용
UM3_SEQ_ENERGIZE_MAX_S = 20.0         # 스펙 §6 열 제약


def wrap_ticks(v) -> int:
    """CA[7] 모듈러 랩: wrap(v)=((v+512)%1024)−512 (스펙 §3)."""
    return int((int(round(v)) + 512) % 1024) - 512


def delta_ticks(delta_deg: float) -> int:
    """Δtick = round(δ̂·512/360) — 양자화 ≤ 0.36° 무시 (스펙 §3)."""
    return int(round(abs(float(delta_deg)) * TICKS_PER_EREV / 360.0))


def _noop_progress(code: str, detail: str) -> None:
    pass


def _never_cancel() -> bool:
    return False


@dataclass
class CommutationIDParams:
    snapshot_dir: str = os.path.join(".omc", "state")
    signature_cap_a: float = 1.30      # 서명 통전 절대상한과 동일 기본
    enable_watch_s: float = 1.5        # S1 idle 폴트 감시창
    flip_ticks: int = FLIP_TICKS_DEFAULT
    max_a_iters: int = 2               # S4 보정 상한 (부호쌍은 별도, enable≤4)
    ca7_sign: Optional[int] = None     # None=1스텝 확정; ±1=동결 상수 사용
    i_ba_ref_a: Optional[float] = None  # 건강 서명 기준 (없으면 프로필에서)
    ka_healthy: Optional[float] = None  # K_a 기준 (HIGH 품질 경로, 선택)
    allow_candidate_b: bool = True
    allow_candidate_c: bool = False    # 봉인 — True는 preflight 거부 (스펙 §1)
    um3_align_i_ladder: Sequence[float] = (2.0, 4.24, 6.0)
    delta_green_deg: float = DELTA_GREEN_DEG
    confirm_expect_slip: bool = True   # 수렴 후 UM3 expect-slip 모순검사 (§2③)
    profile: Optional[object] = None   # motor_profile.MotorProfile (duck-typed)
    synthetic: Optional[bool] = None
    progress_fn: Callable[[str, str], None] = _noop_progress
    cancel_fn: Callable[[], bool] = _never_cancel
    sleep_fn: Callable[[float], None] = time.sleep
    clock_fn: Callable[[], float] = time.monotonic


@dataclass
class CommutationIDResult:
    status: str
    reason: str = ""
    path_used: str = ""                 # A | A+flip | A+B | B  (C는 봉인)
    delta_est_deg: Optional[float] = None
    delta_quality: Optional[str] = None  # HIGH | LOW | BRACKET
    ca7_before: Optional[int] = None
    ca7_after: Optional[int] = None
    ca7_sign_resolved: Optional[int] = None  # s·sign(δ) 곱 — 실기 R3에서 동결
    pending_flip: Optional[int] = None   # 종결 후 적용 대기 중인 CA[7] (C안)
    evidence: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)


class _CIDState:
    """상태기계 가변 상태 (ctx.cid_state)."""

    def __init__(self):
        self.ca7_orig: Optional[int] = None
        self.ca7_cur: Optional[int] = None
        self.cap_a: float = 0.0
        self.i_ba_ref: Optional[float] = None
        self.no_ref = False              # δ 정량 기준 없음 → 플립까지만 수행
        self.pending_flip = None         # 트랜잭션 종결 후 적용할 CA[7] (C안)
        self.orig_override = None        # 2패스 인계: 진짜 원본 CA[7]
        self.band_profile = None
        self.flips = 0
        self.a_iters = 0
        self.enables_a = 0
        self.enables_aux = 0            # UM3 드래그/후보 B의 enable (A예산 밖)
        self.pending: Optional[dict] = None   # 미판정 보정 (부호 반증 대기)
        self.h_confirmed: Optional[int] = None
        self.iterations: list = []
        self.delta_last: Optional[float] = None
        self.q_last: Optional[str] = None
        self.last_i_ba: Optional[float] = None
        self.best_ca7: Optional[int] = None
        self.best_abs_delta: Optional[float] = None
        self.last_mf = None
        self.b_attempted = False
        self.um3_rest_debt_s = 0.0      # 시퀀스 간 휴지 ≥ 통전 (스펙 §6)


# ======================================================================================
# S1 — enable + idle fault watch
# ======================================================================================
def _enable_watch(ctx) -> str:
    """MO=1 → SO=1 폴(≤2 s) → enable_watch_s 동안 idle MF 감시 (지령 없음).

    반환: "STABLE" | "FAULT_0x80" | "OTHER".
    vp._sleep의 _guard는 MF≠0을 즉시 AbortError로 승격시키므로 여기서는
    원시 sleep_fn 폴 루프를 쓴다 — 분류가 이 함수의 존재 이유다."""
    cid = ctx.cid
    st = ctx.cid_state
    # 폴트 래치 해제/멱등 disable (7.5 ms 회복은 폴 주기가 커버)
    vp._cmd(ctx, "MO=0")
    ctx.motor_on = False
    vp._check_cancel(ctx)
    vp._cmd(ctx, "MO=1", allow_motion=True)
    ctx.motor_on = True
    waited = 0.0
    while True:
        so = vp._cmd(ctx, "SO", retries=0)
        mf = vp._cmd(ctx, "MF", retries=0)
        if isinstance(mf, (int, float)) and mf != 0:
            break                        # 폴트 분류는 아래 공통 경로
        if so == 1:
            break
        if waited >= SO_TIMEOUT_S:
            raise vp.AbortError("SO!=1 (%.0fs) — 서보온 실패" % SO_TIMEOUT_S)
        ctx.params.sleep_fn(0.02)
        ctx.elapsed_s += 0.02
        waited += 0.02
        vp._check_cancel(ctx)
    watch = {"watch_s": cid.enable_watch_s, "polls": 0, "mf": 0}
    ctx.evidence.setdefault("enable_watch", []).append(watch)
    t = 0.0
    while True:
        mf = vp._cmd(ctx, "MF", retries=0)
        watch["polls"] += 1
        if isinstance(mf, (int, float)) and mf != 0:
            st.last_mf = int(mf)
            watch["mf"] = st.last_mf
            watch["t_fault_s"] = round(t, 3)
            mo_now = vp._cmd(ctx, "MO", retries=0)
            watch["mo_after_fault"] = mo_now
            ctx.motor_on = (mo_now == 1)
            verdict = ("FAULT_0x80" if int(mf) == MF_SPEED_TRACKING
                       else "OTHER")
            watch["verdict"] = verdict
            return verdict
        if t >= cid.enable_watch_s:
            watch["verdict"] = "STABLE"
            return "STABLE"
        ctx.params.sleep_fn(ENABLE_WATCH_POLL_S)
        ctx.elapsed_s += ENABLE_WATCH_POLL_S
        t += ENABLE_WATCH_POLL_S
        vp._check_cancel(ctx)


# ======================================================================================
# S3 — 서명 측정 + δ 추정
# ======================================================================================
def _measure_signature(ctx) -> dict:
    """서명 램프 1회 (HOLD-CONFIRM, cap=signature_cap_a) → breakaway 증거 사본.

    _breakaway_ramp는 signature_only 모드라 방향 반전/무이탈에서 스스로
    라우팅하지 않고 증거만 남긴다 — 판정은 상태기계 몫."""
    vp._wait_rest(ctx)
    vp._breakaway_ramp(ctx)
    ba = copy.deepcopy(ctx.evidence.get("breakaway") or {})
    st = ctx.cid_state
    if isinstance(ba.get("i_ba_a"), (int, float)):
        st.last_i_ba = float(ba["i_ba_a"])
    return ba


def _delta_estimate(ctx, sig_evidence) -> tuple:
    """(δ̂_deg, quality) — 스펙 §2①②③.

    cap 무이탈 → BRACKET([60,120]° → 90°).  K_a 측정이 공급되고 ka_healthy가
    있으면 c_ka(HIGH, ka_drop 게이트 병기), 아니면 c_iba = clip(ref/meas,0,1)
    (LOW).  direction=−1이면 cos δ<0 반평면: |δ| = 180 − acos(c)."""
    cid = ctx.cid
    st = ctx.cid_state
    ba = sig_evidence or {}
    if not ba.get("detected") or not isinstance(ba.get("i_ba_a"), (int, float)):
        return BRACKET_DELTA_DEG, "BRACKET"
    i_ba = float(ba["i_ba_a"])
    ka_meas = ba.get("k_a_meas")        # (선택) 진단펄스 K_a — 실기 R3 확장점
    if isinstance(ka_meas, (int, float)) and cid.ka_healthy:
        c = min(max(abs(float(ka_meas)) / float(cid.ka_healthy), 0.0), 1.0)
        quality = "HIGH"
        if cid.profile is not None:
            v = physics_gates.ka_drop(abs(float(ka_meas)), cid.profile)
            ctx.evidence["ka_drop_verdict"] = {"status": v.status,
                                               "detail": v.detail}
    else:
        ref = st.i_ba_ref
        if not isinstance(ref, (int, float)) or ref <= 0 or i_ba <= 0:
            return BRACKET_DELTA_DEG, "BRACKET"
        c = min(max(float(ref) / i_ba, 0.0), 1.0)
        quality = "LOW"
    d = math.degrees(math.acos(c))
    if ba.get("direction", 0) == -1:
        d = 180.0 - d                   # cos δ<0 반평면 (S1을 통과했다면 희귀)
    return d, quality


def _converged(ctx, ba, d_est):
    """수렴 = i_ba 대역 GREEN(physics_gates.sig_band) ∧ dir=+1 ∧ |δ̂|≤25.8°."""
    st = ctx.cid_state
    v = physics_gates.sig_band(ba.get("i_ba_a"), st.band_profile)
    ok = (bool(ba.get("detected")) and ba.get("direction", 0) == 1
          and v.status == GREEN and abs(d_est) <= ctx.cid.delta_green_deg)
    return ok, v


# ======================================================================================
# CA[7] 쓰기 규율 (스펙 §3 — MO=0 게이트 · 평문 정수 · 정수 완전일치 되읽기)
# ======================================================================================
def _ca7_write_verified(ctx, value: int) -> None:
    v = int(value)
    if not (CA7_RANGE[0] <= v <= CA7_RANGE[1]):
        raise vp.AbortError("CA[7] 범위 밖 요청(%d) — 쓰기 차단" % v)
    mo = vp._cmd(ctx, "MO")
    if mo != 0:
        vp._cmd(ctx, "MO=0")
        ctx.motor_on = False
    vp._write(ctx, "CA[7]", v)          # _fmt(int) = 평문 정수
    rb = vp._cmd(ctx, "CA[7]")
    if not isinstance(rb, (int, float)) or float(rb) != float(v):
        raise vp.AbortError("CA[7] 되읽기 불일치: 요청 %d, 응답 %r — 차단(RED)"
                            % (v, rb))
    ctx.evidence.setdefault("ca7_trail", []).append(v)


# ======================================================================================
# UM3 프리미티브 래퍼 (전류 파라미터화 — autotune_velpos._um3_drag 재사용)
# ======================================================================================
def _um3_expect_slip(ctx, i_test_a) -> dict:
    """스펙 §2③: I_test에서 UM3 스텝스윕 — 슬립 ⟺ δ<45°(건강), 추종 ⟺ 오염."""
    return vp._um3_drag(ctx, float(i_test_a), expect_slip=True)


def _um3_rest(ctx, energize_s: float):
    """UM3 열 계약: 시퀀스 간 휴지 ≥ 직전 통전 시간 (스펙 §6)."""
    if energize_s > 0:
        vp._sleep(ctx, float(energize_s))


# ======================================================================================
# 후보 B — CS 앵커 (스펙 §5)
# ======================================================================================
def _um3_align_cs(ctx, i_ladder) -> dict:
    """UM3 정렬(단방향 당김+정착) → CS=0 → UM5 복원 → S1 → 서명 검증.

    사다리 소진 시 AbortError("후보 B 실패 ... CS ... 생존 실패 의심") —
    호출자는 CA[7]을 이미 원복해 둔 상태다."""
    cid = ctx.cid
    st = ctx.cid_state
    st.b_attempted = True
    bev = {"anchor_pa_ticks": B_ANCHOR_PA_TICKS, "cs_value": 0,
           "rungs": [], "established": False}
    ctx.evidence["candidate_b"] = bev
    for i_align in i_ladder:
        i_align = float(i_align)
        rung = {"i_align_a": i_align}
        bev["rungs"].append(rung)
        vp._emit(ctx, "S5_CAP", "후보 B 정렬: UM3 TC=%.2fA, PA→%d(스텝 %dtick)"
                 % (i_align, B_ANCHOR_PA_TICKS, B_PA_STEP_TICKS))
        t0 = ctx.elapsed_s
        vp._cmd(ctx, "MO=0")
        ctx.motor_on = False
        vp._write(ctx, "UM", 3)
        try:
            vp._check_cancel_before_mutation(ctx)
            vp._cmd(ctx, "MO=1", allow_motion=True)
            ctx.motor_on = True
            st.enables_aux += 1
            vp._seg(ctx, "tc")
            for k in range(1, B_TC_RAMP_STEPS + 1):
                vp._write(ctx, "TC", i_align * k / B_TC_RAMP_STEPS,
                          allow_motion=True)
                vp._sleep(ctx, B_TC_RAMP_STEP_S)
            pa_rd = vp._cmd(ctx, "PA", allow_motion=True)
            pa0 = (int(round(float(pa_rd)))
                   if isinstance(pa_rd, (int, float)) else 0)
            total = B_ANCHOR_PA_TICKS - pa0
            nsteps = max(1, int(math.ceil(abs(total) / float(B_PA_STEP_TICKS))))
            for k in range(1, nsteps + 1):
                vp._write(ctx, "PA", int(round(pa0 + total * k / nsteps)),
                          allow_motion=True)
                vp._cmd(ctx, "BG", allow_motion=True)   # PA는 BG에서만 발효
                vp._sleep(ctx, vp.UM3_STEP_S)
            vp._wait_rest(ctx)
            vp._cmd(ctx, "CS=0", allow_motion=True)     # RAM 즉시 (CR p62)
            rung["cs_written"] = True
        finally:
            vp._seg(ctx, "idle")
            try:
                vp._cmd(ctx, "TC=0", allow_motion=True, retries=0)
            except Exception:
                pass
            try:
                vp._cmd(ctx, "MO=0", retries=0)
                ctx.motor_on = False
                vp._cmd(ctx, "UM=%s" % vp._fmt(ctx.snapshot.get("UM", 5)),
                        retries=0)
            except Exception as e:
                ctx.warnings.append("후보 B UM 복원 실패(%s) — abort 체인이"
                                    " 재시도" % e)
        energize = max(ctx.elapsed_s - t0, 0.0)
        rung["energize_s"] = round(energize, 2)
        if energize > UM3_SEQ_ENERGIZE_MAX_S:
            raise vp.AbortError("후보 B: UM3 통전 %.1fs > %.0fs 열 제약 — 중단"
                                % (energize, UM3_SEQ_ENERGIZE_MAX_S))
        # 검증: UM5 복귀 후 enable-watch + 서명 (CS 생존의 실질 심판)
        watch = _enable_watch(ctx)
        st.enables_aux += 1
        if watch != "STABLE":
            rung["verdict"] = ("검증 enable 폴트(%s, MF=0x%X) — CS UM=5 복귀"
                               " 후 미생존 지문" % (watch, st.last_mf or 0))
            _um3_rest(ctx, energize)
            continue
        ba = _measure_signature(ctx)
        d_est, q = _delta_estimate(ctx, ba)
        ok, v_band = _converged(ctx, ba, d_est)
        rung["signature"] = {"i_ba_a": ba.get("i_ba_a"),
                             "direction": ba.get("direction"),
                             "delta_est_deg": round(d_est, 2), "quality": q,
                             "band": v_band.status, "pass": bool(ok)}
        if ok:
            bev["established"] = True
            st.delta_last, st.q_last = d_est, q
            return bev
        rung["verdict"] = "복귀 후 서명 불합격 — 다음 사다리 단"
        _um3_rest(ctx, energize)
    raise vp.AbortError(
        "후보 B 실패: CS 앵커 확립 불가 — UM3 정렬 사다리(%s A) 전 단에서 UM=5"
        " 복귀 후 서명/enable 불합격 = CS가 UM=5 복귀를 생존하지 못함 의심"
        " (스펙 §5 실기확인 (i)); CA[7]은 원본 유지, 정직 RED"
        % ",".join("%.2f" % float(x) for x in i_ladder))


# ======================================================================================
# 결과/종결 헬퍼
# ======================================================================================
def _read_ca7_final(ctx):
    try:
        rb = vp._cmd(ctx, "CA[7]", retries=0)
        return int(rb) if isinstance(rb, (int, float)) else None
    except Exception:
        return None


def _build_result(ctx, st, status, reason, path) -> CommutationIDResult:
    ctx.evidence.setdefault("readings", ctx.readings)
    ctx.evidence["iterations"] = st.iterations
    ctx.evidence["enables"] = {"a_path": st.enables_a, "aux": st.enables_aux,
                               "budget_a": A_ENABLE_BUDGET}
    ctx.evidence["flips"] = st.flips
    ctx.evidence["a_iters"] = st.a_iters
    if st.best_ca7 is not None:
        ctx.evidence["best_ca7"] = st.best_ca7
    return CommutationIDResult(
        status=status, reason=reason, path_used=path,
        delta_est_deg=st.delta_last, delta_quality=st.q_last,
        ca7_before=st.ca7_orig, ca7_after=_read_ca7_final(ctx),
        ca7_sign_resolved=st.h_confirmed, pending_flip=st.pending_flip,
        evidence=ctx.evidence, warnings=ctx.warnings)


def _path_of(st) -> str:
    if st.b_attempted:
        return "B" if st.a_iters == 0 else "A+B"
    return "A+flip" if st.flips else "A"


def _close(ctx, st, status, reason, path) -> CommutationIDResult:
    """S6 CLOSE: _do_abort(TC=0/MO=0/UM/리밋) → 종료상태 검증 → 판정."""
    vp._emit(ctx, "S6_CLOSE", "안전 종료: %s" % (reason or "측정 완료"))
    vp._do_abort(ctx, reason or "커뮤테이션 ID 측정 완료 — 안전 종료")
    final_ok = vp._capture_signature_final_state(ctx)
    if not final_ok:
        return _build_result(ctx, st, RED,
                             vp._signature_final_state_failure(ctx), path)
    return _build_result(ctx, st, status, reason, path)


def _fail_close(ctx, st, reason) -> CommutationIDResult:
    """모든 실패 종료: abort 체인 + CA[7] 원복(실패 시 RED 사유 병기)."""
    vp._do_abort(ctx, reason)
    if st.ca7_orig is not None:
        try:
            cur = vp._cmd(ctx, "CA[7]", retries=0)
            if not isinstance(cur, (int, float)) or int(cur) != st.ca7_orig:
                vp._cmd(ctx, "CA[7]=%d" % st.ca7_orig, retries=1)
                rb = vp._cmd(ctx, "CA[7]", retries=0)
                if not isinstance(rb, (int, float)) \
                        or int(rb) != st.ca7_orig:
                    raise RuntimeError("되읽기 %r != %d" % (rb, st.ca7_orig))
            st.ca7_cur = st.ca7_orig
            ctx.evidence["ca7_restore"] = {"restored_to": st.ca7_orig,
                                           "pass": True}
        except Exception as e:
            reason = "%s; CA[7] 원복 실패(%s) — RED" % (reason, e)
            ctx.evidence["ca7_restore"] = {"pass": False, "error": str(e)}
    final_ok = vp._capture_signature_final_state(ctx)
    if not final_ok:
        reason = "%s; %s" % (reason, vp._signature_final_state_failure(ctx))
    return _build_result(ctx, st, RED, reason, _path_of(st))


# ======================================================================================
# 상태기계 본체
# ======================================================================================
def _validate_params(cid: CommutationIDParams):
    cap = cid.signature_cap_a
    if (not isinstance(cap, (int, float)) or not math.isfinite(cap)
            or cap <= 0.0
            or cap > vp.SIGNATURE_ENERGIZE_ABS_MAX_A + 1e-12):
        raise vp.PreflightError(
            "서명 통전 상한은 0 < cap <= %.2f A(안전천장) — 명시 초과 요청은"
            " 거부 (요청값=%r)" % (vp.SIGNATURE_ENERGIZE_ABS_MAX_A, cap))
    if cid.allow_candidate_c:
        raise vp.PreflightError(
            "후보 C(내장 커뮤 서치)는 봉인 상태 — EC36/CA[17] 리셋모순 실기"
            " 미확정 (allow_candidate_c=False 고정, 스펙 §1)")
    if cid.max_a_iters < 0:
        raise vp.PreflightError("max_a_iters >= 0 필요 (%r)" % cid.max_a_iters)
    if cid.flip_ticks != FLIP_TICKS_DEFAULT:
        raise vp.PreflightError(
            "flip_ticks는 256(=180° elec) 고정 — §1.1 따름정리가 성립하는"
            " 유일한 값 (요청 %r)" % (cid.flip_ticks,))
    for i in cid.um3_align_i_ladder:
        if not (0.0 < float(i) <= UM3_LADDER_MAX_A + 1e-12):
            raise vp.PreflightError(
                "UM3 사다리 전류는 0 < I <= %.1f A (8.49 A는 오퍼레이터 승인"
                " 전용 — 자동 경로 금지): %r" % (UM3_LADDER_MAX_A, i))
    if len(tuple(cid.um3_align_i_ladder)) > 3:
        raise vp.PreflightError("UM3 사다리는 최대 3단 (스펙 §5)")


def _resolve_ref(cid: CommutationIDParams):
    if isinstance(cid.i_ba_ref_a, (int, float)) and cid.i_ba_ref_a > 0:
        return float(cid.i_ba_ref_a)
    band = getattr(cid.profile, "signature_band", None)
    if isinstance(band, dict):
        r = band.get("i_ba_ref_a")
        if isinstance(r, (int, float)) and r > 0:
            return float(r)
    return None


def _s0_snapshot(ctx, st):
    cid = ctx.cid
    if not getattr(ctx.link, "is_connected", False):
        raise vp.PreflightError("드라이브 미연결")
    if vp._cmd(ctx, "MO") == 1:
        raise vp.PreflightError("모터 ON(MO=1) — STOP 후 재시도 (자동 disable"
                                " 금지)")
    for c in vp._P1_READS:
        ctx.readings[c] = vp._cmd(ctx, c)
    for c in vp._P1_READS_OPT:
        try:
            ctx.readings[c] = vp._cmd(ctx, c, retries=0)
        except Exception:
            ctx.readings[c] = None
    ctx.evidence["readings"] = dict(ctx.readings)
    r = ctx.readings
    ts = r.get("TS")
    if not isinstance(ts, (int, float)) or not (40 <= ts <= 200):
        raise vp.PreflightError("TS=%r 비정상" % (ts,))
    ctx.ts_s = ts * 1e-6
    if r.get("UM") != 5:
        raise vp.PreflightError("UM=%r (5 필요)" % (r.get("UM"),))
    # MF=0x80(speed tracking)은 cos δ<0의 enable-time 증상이자 **이 알고리즘이
    # 처리하도록 설계된 바로 그 폴트**다(S1 감지 → S2 플립).  그것 때문에 시작을
    # 거부하면 매번 전원 재인가를 강요하고, 전원 재인가는 RAM의 CA[7] 진전까지
    # 되돌려 악순환이 된다(실기 2026-07-21).  MF는 다음 MO=1에서 클리어되고 S1이
    # 직접 재관측하므로, 정확히 0x80일 때만 진행을 허용한다 — 다른 폴트는 거부.
    mf = r.get("MF")
    if not isinstance(mf, (int, float)) or int(mf) not in (0, MF_SPEED_TRACKING):
        raise vp.PreflightError("시작 시 모터 폴트 MF=%r — 수동 확인 후 재시도"
                                % (mf,))
    if int(mf) == MF_SPEED_TRACKING:
        ctx.warnings.append(
            "시작 시 MF=0x80(speed tracking) 래치 — 이 알고리즘이 처리하는 폴트라"
            " 진행(다음 MO=1에서 클리어, S1이 재관측)")
    if r.get("CA[17]") != 5:
        raise vp.PreflightError("CA[17]=%r (5=시리얼 절대 무모션 필요 — 다른"
                                " 커뮤 방법 감지, 수동 확인)" % (r.get("CA[17]"),))
    cl1 = r.get("CL[1]")
    if not isinstance(cl1, (int, float)) or cl1 <= 0:
        raise vp.PreflightError("CL[1]=%r 비정상" % (cl1,))
    ctx.cl1 = float(cl1)
    ca18 = r.get("CA[18]")
    if not isinstance(ca18, (int, float)) or ca18 <= 0:
        raise vp.PreflightError("CA[18]=%r 비정상" % (ca18,))
    ctx.ca18 = float(ca18)
    ctx.vx_guard_cnt = ctx.ca18 * vp.GUARD_RPM / 60.0
    ca19 = r.get("CA[19]")
    if not isinstance(ca19, (int, float)) or ca19 <= 0:
        raise vp.PreflightError("CA[19]=%r 비정상 — UM3 판별/후보 B에 필수"
                                % (ca19,))
    ca7 = r.get("CA[7]")
    if not isinstance(ca7, (int, float)) or not float(ca7).is_integer() \
            or not (CA7_RANGE[0] <= ca7 <= CA7_RANGE[1]):
        raise vp.PreflightError("CA[7]=%r 비정상(정수 −512..512 기대)" % (ca7,))
    st.ca7_orig = st.ca7_cur = int(ca7)
    if st.orig_override is not None:
        # 2패스: S0가 읽은 값은 이미 플립된 값이므로, 원복 목표는 첫 패스의 원본
        st.ca7_orig = int(st.orig_override)
    st.cap_a = float(cid.signature_cap_a)
    if st.cap_a > ctx.cl1:
        raise vp.PreflightError("cap %.2fA > CL[1]=%.2fA" % (st.cap_a, ctx.cl1))
    st.i_ba_ref = _resolve_ref(cid)
    # δ 정량(S3 측정 / S4 정밀 보정)에는 건강 기준이 필요하지만, S1 enable-watch와
    # S2 180° 플립은 MF=0x80 신호만으로 성립한다(스펙 §1.1 따름정리).  기준이 없다고
    # 거친 보정 경로까지 막으면 첫 런이 부트스트랩 순환에 갇힌다 — 기준은 서명 GREEN
    # 에서 생기고, 서명은 커뮤가 나쁘면(cos δ<0, enable 즉시 MF=0x80) 못 돈다.
    # 그래서 기준 없이도 플립까지는 수행하고 S3에서 정직하게 YELLOW로 종료한다.
    # (실기 2026-07-21: CA[7]=322에서 enable마다 MF=128 재현 → 이 경로가 유일한 해제)
    st.no_ref = st.i_ba_ref is None and not cid.ka_healthy
    if st.no_ref:
        ctx.warnings.append(
            "δ 추정 기준 없음(i_ba_ref/ka_healthy) — enable-watch + 180° 플립까지만"
            " 수행하고 정밀 보정은 생략 (서명으로 베이스라인 확립 후 재실행)")
    st.band_profile = (cid.profile if _resolve_ref(cid) is not None
                       and getattr(cid.profile, "signature_band", None)
                       else SimpleNamespace(
                           signature_band={"i_ba_ref_a": st.i_ba_ref},
                           cont_current_a=ctx.cl1))
    # 서명 램프 상한을 절대 cap으로 치환 (vp signature_only 관례)
    ctx.params = _dc_replace(ctx.params, ramp_frac=st.cap_a / ctx.cl1,
                             signature_cap_a=st.cap_a)
    try:
        vp._resolve_signals(ctx)
    except vp.PreflightError as e:
        ctx.warnings.append("레코더 신호 미확보(%s) — 램프 레코딩 없이 진행"
                            % e)
    ctx.snapshot = dict(ctx.readings)
    os.makedirs(ctx.params.snapshot_dir, exist_ok=True)
    ctx.snapshot_path = os.path.join(
        ctx.params.snapshot_dir,
        "commutation_id_snapshot_%d.json" % int(time.time() * 1000))
    with open(ctx.snapshot_path, "w", encoding="utf-8") as fj:
        json.dump({"t": time.time(), "readings": ctx.snapshot}, fj,
                  ensure_ascii=False, indent=1)
    ctx.evidence["snapshot_path"] = ctx.snapshot_path
    vp._apply_limits_verified(ctx)
    vp._emit(ctx, "S0_SNAPSHOT",
             "스냅숏 %s: CA[7]=%d CA[17]=5 UM=5 CL[1]=%.2fA cap=%.2fA"
             % (ctx.snapshot_path, st.ca7_orig, ctx.cl1, st.cap_a))


def _revert_and_opposite(ctx, st, cause: str):
    """보정 가설 반증: 직전 보정을 원복하고 반대 부호로 재적용 (같은 반복)."""
    p = st.pending
    st.pending = None
    _ca7_write_verified(ctx, p["ca7_pre"])
    st.ca7_cur = p["ca7_pre"]
    h2 = -p["h"]
    # 부호 확정은 첫 보정(반복 1)의 반증에서만 — 이후 반복은 δ의 부호가 이미
    # 뒤집혔을 수 있어 s·sign(δ) 곱의 혼동이 커진다 (모듈 docstring 참조)
    if p["iter_no"] == 1 and st.h_confirmed is None:
        st.h_confirmed = h2
    new = wrap_ticks(p["ca7_pre"] - h2 * p["dtick"])
    _ca7_write_verified(ctx, new)
    st.ca7_cur = new
    st.iterations.append({
        "event": "sign_pair", "cause": cause, "h_first": p["h"],
        "h_second": h2, "dtick": p["dtick"], "ca7": new,
        "note": "부호 가설쌍 — max_a_iters 캡에 셈하지 않음 (스펙 §3)"})
    vp._emit(ctx, "S4_CORRECT",
             "부호 반증(%s): 원복 후 반대 부호 h=%+d 재적용 → CA[7]=%d"
             % (cause, h2, new))


def _s4_correct(ctx, st, d_est, quality):
    dtick = delta_ticks(d_est)
    if dtick == 0:
        raise vp.AbortError("δ̂=%.2f°≈0인데 서명 불합격 — CA[7] 보정으로 해소"
                            " 불가(비-각도 원인 의심), 정직 RED" % d_est)
    h = (st.h_confirmed if st.h_confirmed is not None
         else (ctx.cid.ca7_sign if ctx.cid.ca7_sign else 1))
    new = wrap_ticks(st.ca7_cur - h * dtick)
    _ca7_write_verified(ctx, new)
    st.a_iters += 1
    st.pending = {"ca7_pre": st.ca7_cur, "d_pre": abs(d_est), "h": h,
                  "dtick": dtick, "bracket": quality == "BRACKET",
                  "iter_no": st.a_iters}
    st.ca7_cur = new
    st.iterations.append({"event": "correct", "iter": st.a_iters,
                          "delta_est_deg": round(d_est, 2),
                          "quality": quality, "h": h, "dtick": dtick,
                          "ca7": new})
    vp._emit(ctx, "S4_CORRECT",
             "보정 #%d: δ̂=%.1f°(%s) Δtick=%d h=%+d → CA[7]=%d (MO=1 재계산"
             " 경유)" % (st.a_iters, d_est, quality, dtick, h, new))


def _s2_double_fault(ctx, st) -> CommutationIDResult:
    """플립 양측 폴트 = δ 원인 아님(§1.1 따름정리) → UM3 판별 → 정직 RED."""
    vp._emit(ctx, "S2_FLIP", "플립 양측 모두 MF=0x80 — δ 원인 배제, UM3 판별")
    drag_note = "UM3 판별 불가"
    try:
        i_probe = float(ctx.cid.um3_align_i_ladder[0])
        drag = vp._um3_drag(ctx, i_probe)
        if drag and drag.get("pa_effective", True) \
                and isinstance(drag.get("follow_ratio"), (int, float)):
            fr = drag["follow_ratio"]
            if fr >= vp.UM3_FOLLOW_MIN:
                drag_note = ("UM3 추종 %.2f — 스테이터/기계 구동 정상: 폴트는"
                             " 커뮤 각도 문제가 아님" % fr)
            else:
                drag_note = ("UM3 미추종 %.2f — 기계 구속/부하 의심" % fr)
    except (vp.AbortError, PermissionError):
        raise
    except Exception as e:
        ctx.warnings.append("이중폴트 UM3 판별 예외(%r) — 판별 없이 보고" % (e,))
    raise vp.AbortError(
        "비-커뮤 원인: 180° 플립 양측에서 MF=0x%X — cos δ와 cos(δ−180°)는 동시"
        " 음 불가(§1.1). %s. 배선/엔코더/부하/드라이브 점검 필요; CA[7] 원복"
        % (st.last_mf or MF_SPEED_TRACKING, drag_note))


def _s5_cap(ctx, st, why: str) -> CommutationIDResult:
    """A 소진: CA[7] 원본복원(best는 evidence만) → 후보 B 또는 정직 RED."""
    cid = ctx.cid
    vp._emit(ctx, "S5_CAP", "%s — CA[7] 원본복원 후 %s"
             % (why, "후보 B(CS)" if cid.allow_candidate_b else "정직 RED"))
    vp._cmd(ctx, "MO=0")
    ctx.motor_on = False
    if st.ca7_cur != st.ca7_orig:
        _ca7_write_verified(ctx, st.ca7_orig)
        st.ca7_cur = st.ca7_orig
    if not cid.allow_candidate_b:
        raise vp.AbortError(
            "%s — 후보 B 비활성(allow_candidate_b=False): 3회째 보정 없음,"
            " CA[7] 원복, 정직 RED" % why)
    _um3_align_cs(ctx, cid.um3_align_i_ladder)   # 실패 시 AbortError
    return _close(
        ctx, st, YELLOW,
        "커뮤 확립 = 후보 B(CS 앵커) — 세션한정(CS): RAM 전용이라 SV로 보존"
        " 불가, 전원 재인가 시 재실행 필요 (%s)" % why,
        _path_of(st))


def _machine(ctx, st) -> CommutationIDResult:
    cid = ctx.cid
    _validate_params(cid)
    _s0_snapshot(ctx, st)
    while True:
        # ---- S1 ENABLE-WATCH ------------------------------------------------
        if st.enables_a >= A_ENABLE_BUDGET:
            return _s5_cap(ctx, st,
                           "총 enable 예산(%d) 소진" % A_ENABLE_BUDGET)
        st.enables_a += 1
        vp._emit(ctx, "S1_WATCH", "enable #%d + idle 감시 %.1fs (MF 폴 50ms)"
                 % (st.enables_a, cid.enable_watch_s))
        watch = _enable_watch(ctx)
        if watch == "OTHER":
            raise vp.AbortError("enable-watch 비-0x80 폴트 MF=0x%X — 커뮤 ID"
                                " 범위 밖, 수동 점검" % (st.last_mf or 0))
        if watch == "FAULT_0x80":
            if st.pending is not None:
                # 보정 직후 폴트 = |δ|가 90°를 넘음 = 보정 방향이 틀림
                _revert_and_opposite(ctx, st, cause="fault")
                continue
            if st.flips == 0:
                # 자기 데드락 회피 (실기 2026-07-21): 이 런의 임시 안전리밋은
                # P2_LIMITS persistence 트랜잭션이라, 살아 있는 동안
                # persistence_unknown=True가 되어 CA[7] 같은 일반 할당이 전부
                # 차단된다("command blocked: persistence state UNKNOWN").
                # 리밋은 '통전'을 보호하는 것이지 무모션 파라미터 쓰기를 보호하지
                # 않으므로, 여기서 바로 쓰지 않고 플립을 '요청'으로 남기고 정상
                # 종결한다 — run_commutation_id가 트랜잭션이 닫힌 사이에 쓰고
                # 한 번 재실행한다 (트랜잭션 2분할).
                st.flips = 1
                new = wrap_ticks(st.ca7_cur + cid.flip_ticks)
                st.pending_flip = new
                st.iterations.append({"event": "flip_requested", "ca7": new})
                vp._emit(ctx, "S2_FLIP",
                         "MF=0x80 idle — 180° 플립 요청: CA[7] %d→%d"
                         " (리밋 종결 후 적용·재실행)" % (st.ca7_cur, new))
                return _close(ctx, st, YELLOW,
                              "180° 플립 적용 대기 — 리밋 트랜잭션 종결 후"
                              " CA[7]=%d 쓰기 후 재실행" % new, _path_of(st))
            return _s2_double_fault(ctx, st)
        # ---- S3 MEASURE -----------------------------------------------------
        if st.no_ref:
            # 기준 없음 → δ 정량 불가.  거친 보정(플립)까지가 이 런의 범위다.
            # enable이 이 지점에 도달했다는 것 자체가 "폴트 없이 통전 유지"의
            # 증거이므로, 플립을 적용했다면 그 CA[7]을 유지한 채 종료한다
            # (CA[7]은 SV 전까지 RAM — 전원 재인가로 원복 가능).
            if st.flips:
                return _close(ctx, st, YELLOW,
                              "180° 플립 적용 후 인에이블 안정 — CA[7]=%d 유지."
                              " 서명으로 베이스라인 확립 후 정밀 보정 재실행"
                              % st.ca7_cur, _path_of(st))
            return _close(ctx, st, YELLOW,
                          "인에이블 안정(폴트 없음) · δ 정량 불가(기준 없음) —"
                          " 서명으로 베이스라인 확립 후 재실행", _path_of(st))
        vp._emit(ctx, "S3_MEASURE", "서명 램프(≤%.2fA, HOLD-CONFIRM)"
                 % st.cap_a)
        ba = _measure_signature(ctx)
        d_est, quality = _delta_estimate(ctx, ba)
        ok, v_band = _converged(ctx, ba, d_est)
        st.iterations.append({
            "event": "measure", "ca7": st.ca7_cur,
            "i_ba_a": ba.get("i_ba_a"), "detected": bool(ba.get("detected")),
            "direction": ba.get("direction"),
            "delta_est_deg": round(d_est, 2), "quality": quality,
            "band": v_band.status, "converged": bool(ok)})
        if st.best_abs_delta is None or abs(d_est) < st.best_abs_delta:
            st.best_abs_delta = abs(d_est)
            st.best_ca7 = st.ca7_cur
        # ---- 부호 가설 판정 (직전 보정의 재측정) ----------------------------
        if st.pending is not None:
            p = st.pending
            if not p["bracket"] and quality != "BRACKET":
                if abs(d_est) < IMPROVE_FRAC * p["d_pre"]:
                    if p["iter_no"] == 1 and st.h_confirmed is None:
                        st.h_confirmed = p["h"]     # 개선 = 가설 확정
                    st.pending = None
                else:
                    _revert_and_opposite(ctx, st, cause="measured_worse")
                    continue
            else:
                st.pending = None       # BRACKET 개입 — 판정 불가, 가설 유지
        st.delta_last, st.q_last = d_est, quality
        if ok:
            # ---- 수렴: (선택) UM3 expect-slip 모순검사 (§2③) ---------------
            if cid.confirm_expect_slip and quality != "HIGH" \
                    and isinstance(st.last_i_ba, (int, float)):
                i_test, dd = physics_gates.derive_drag_current(
                    ctx.cl1, i_ba_meas_a=st.last_i_ba)
                ctx.evidence["expect_slip_derivation"] = dd
                drag = _um3_expect_slip(ctx, i_test)
                fr = (drag.get("follow_ratio")
                      if drag and drag.get("pa_effective", True) else None)
                st.enables_aux += 1
                v = physics_gates.sig_first_run(True, fr, ka_ok=False)
                ctx.evidence["expect_slip_verdict"] = {
                    "status": v.status, "detail": v.detail}
                if v.status == RED:
                    raise vp.AbortError(
                        "expect-slip 모순: UM3가 I=%.2fA(=i_ba/√2)를 추종"
                        "(follow=%.2f≥%.1f) — δ≥45° 재오염 의심, 수렴 판정"
                        " 철회" % (i_test,
                                   fr if fr is not None else -1.0,
                                   physics_gates.UM3_FOLLOW))
            return _close(ctx, st, GREEN, "", _path_of(st))
        if st.a_iters >= cid.max_a_iters:
            return _s5_cap(ctx, st,
                           "A 보정 상한(max_a_iters=%d) 소진" % cid.max_a_iters)
        _s4_correct(ctx, st, d_est, quality)


# ======================================================================================
# 진입점
# ======================================================================================
def _parse_int(raw) -> Optional[int]:
    if raw is None:
        return None
    m = re.search(r"[-+]?\d+", str(raw))
    return int(m.group(0)) if m else None


def _write_ca7_between_runs(link, value: int) -> tuple:
    """리밋 트랜잭션이 닫힌 사이에 CA[7]을 쓰고 정수 되읽기로 검증한다.

    이 경로에서만 persistence 가드가 열려 있다(활성 P2_LIMITS 기록 없음).
    MO=0에서만 쓰고, SV는 보내지 않는다(RAM 전용 — 전원 재인가로 원복).
    반환: (ok, detail)
    """
    v = int(value)
    if not (CA7_RANGE[0] <= v <= CA7_RANGE[1]):
        return False, "CA[7] 범위 밖(%d)" % v
    try:
        mo = _parse_int(link.command("MO"))
        if mo != 0:
            return False, "MO=%r (0 필요)" % mo
        link.command("CA[7]=%d" % v)
        back = _parse_int(link.command("CA[7]"))
    except Exception as exc:                                  # noqa: BLE001
        return False, "%s: %s" % (type(exc).__name__, exc)
    if back != v:
        return False, "되읽기 불일치 요청=%d 응답=%r" % (v, back)
    return True, "CA[7]=%d 되읽기 검증" % v


def run_commutation_id(link, params: Optional[CommutationIDParams] = None
                       ) -> CommutationIDResult:
    """커뮤테이션 자립 ID (스펙 §4) — 트랜잭션 2분할 래퍼.

    S2가 플립을 요청하면 내부 런은 리밋을 정상 종결하고 반환한다.  그 사이
    (활성 persistence 기록 없음)에 CA[7]을 쓰고 한 번만 재실행한다.  절대
    raise하지 않으며 SV는 보내지 않는다.
    """
    params = params or CommutationIDParams()
    res = _run_once(link, params)
    pending = res.pending_flip
    if pending is None:
        return res
    ok, detail = _write_ca7_between_runs(link, pending)
    if not ok:
        res.warnings.append("180° 플립 적용 실패(%s) — CA[7] 미변경" % detail)
        return _dc_replace(res, status=RED,
                           reason="180° 플립 적용 실패: %s" % detail)
    res2 = _run_once(link, params, prior_flips=1,
                     orig_ca7=res.ca7_before)
    res2.warnings.insert(0, "180° 플립 적용 후 재실행 (%s)" % detail)
    # 두 패스를 하나의 오퍼레이션으로 합성한다 — 소비자에게 이것은 "플립을 포함한
    # 한 번의 커뮤 ID"이지 별개의 두 런이 아니다.  ca7_before는 첫 패스의 원본을,
    # 폴트/enable 이력은 두 패스를 이어붙여 보고한다.
    ev1 = res.evidence or {}
    ev2 = res2.evidence or {}
    merged = dict(ev2)
    merged["flips"] = int(ev2.get("flips", 0))   # prior_flips로 이미 시드됨
    merged["enable_watch"] = (list(ev1.get("enable_watch", []))
                              + list(ev2.get("enable_watch", [])))
    merged["iterations"] = (list(ev1.get("iterations", []))
                            + list(ev2.get("iterations", [])))
    e1, e2 = ev1.get("enables", {}) or {}, ev2.get("enables", {}) or {}
    merged["enables"] = {
        "a_path": int(e1.get("a_path", 0)) + int(e2.get("a_path", 0)),
        "aux": int(e1.get("aux", 0)) + int(e2.get("aux", 0)),
        "budget_a": A_ENABLE_BUDGET}
    merged["flip_applied_between_runs"] = {
        "ca7": int(pending), "detail": detail,
        "first_pass_reason": res.reason}
    reason2 = res2.reason or ""
    if "플립" not in reason2:
        reason2 = "180° 플립 적용 후: " + reason2
    return _dc_replace(
        res2, evidence=merged, reason=reason2, pending_flip=None,
        warnings=list(res.warnings) + list(res2.warnings),
        ca7_before=(res.ca7_before if res.ca7_before is not None
                    else res2.ca7_before),
        path_used=("A+flip" if res2.path_used == "A" else res2.path_used))


def _run_once(link, params: CommutationIDParams, prior_flips: int = 0,
              orig_ca7: Optional[int] = None) -> CommutationIDResult:
    """한 번의 ctx 수명주기(리밋 적용→…→종결).  플립 요청 시 조기 종결한다.

    prior_flips/orig_ca7 = 2패스 인계 — 이미 플립을 한 번 썼다는 사실과 진짜
    원본 CA[7]을 알려준다.  이게 없으면 2패스가 또 플립을 요청하고(무한),
    이중폴트(δ 원인 배제) 판정과 CA[7] 원복 목표가 틀어진다.
    """
    synthetic = (params.synthetic if params.synthetic is not None
                 else bool(getattr(link, "is_synthetic", False)))
    snap_dir = (os.path.join(params.snapshot_dir, vp.SYNTHETIC_SUBDIR)
                if synthetic else params.snapshot_dir)
    vp_params = vp.AutotuneVPParams(
        signature_only=True, snapshot_dir=snap_dir,
        sleep_fn=params.sleep_fn, clock_fn=params.clock_fn,
        progress_fn=params.progress_fn, cancel_fn=params.cancel_fn,
        profile=params.profile, synthetic=synthetic)
    ctx = vp._Ctx(link, vp_params)
    ctx.cid = params
    st = _CIDState()
    st.flips = int(prior_flips)
    st.orig_override = orig_ca7
    ctx.cid_state = st
    if synthetic:
        ctx.evidence["synthetic_quarantine"] = snap_dir
    try:
        return _machine(ctx, st)
    except vp.PreflightError as e:
        # 드라이브 변이 이전 실패 (리밋 적용 후라면 finally-net이 커버)
        return _build_result(ctx, st, RED, str(e), _path_of(st))
    except vp.AbortError as e:
        return _fail_close(ctx, st, str(e))
    except Exception as e:                       # 절대 raise하지 않는다
        return _fail_close(ctx, st, "내부 예외: %r" % (e,))
    finally:
        vp._ensure_limits_closeout(ctx)
