"""MotorProfile — 회전형 모터 단일 진실원 (P1, 완전 오프라인).

어떤 모터가 연결되든 그 모터의 정체·정격·리밋을 담는 **불변** 레코드.
드라이브 리드(VH[2]/CA[18]/CA[19]/CA[28]/CL[1]/PL[1]/TS)와 사용자 입력
(Motor Settings maxspeed, pole_pairs)을 합성해 만들며, 이후 단계
(P2 상한 파생 · P3 게이트 · P4 커뮤)의 입력 계약이 된다.

계약 (고정 — 재량 없음):
  * ``rated_rpm_drive = VH[2] * 60 / CA[18]``  [counts/s * s/min / (counts/rev) = rpm]
  * ``rated_rpm_user``  = Motor Settings maxspeed 필드값 [rpm]
  * ``effective_rated_rpm = min(drive, user)``  (fail-closed)
  * 두 소스 편차 > 5% -> ``rated_rpm_flag = "YELLOW"``, 아니면 ``"GREEN"``.
    한쪽만 있으면 그 값을 쓰고 ``"DRIVE_ONLY"`` / ``"USER_ONLY"``로 표기.
    양쪽 다 없으면 ``"NEED_DATA"`` (프로필 무효).
  * ``pole_pairs``: CA[19] 판독 가능하면 그 값. 판독불가 시 **16 폴백 금지**
    -> 사용자 입력이 없으면 ``pole_pairs_state = "NEED_DATA"`` 이고 프로필은
    유효하지 않다 (``is_valid == False``).
  * per-profile 영속: 이름(motor id) 키의 개별 JSON
    (``snapshot_dir/motor_profiles/<slug>.json``) — 다중 모터 교차오염 방지.
  * ka_baseline · signature_band · i_ba_history 는 P2+에서 채울 자리만 확보.

이 모듈은 기존 코드를 일절 수정하지 않으며 드라이브/DLL/시리얼을 만지지
않는다 (순수 파이썬 + json + os).
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Tuple

SCHEMA_VERSION = 1

# rated_rpm_flag values
FLAG_GREEN = "GREEN"            # both sources present, deviation <= 5 %
FLAG_YELLOW = "YELLOW"          # both sources present, deviation  > 5 %
FLAG_DRIVE_ONLY = "DRIVE_ONLY"  # only drive-derived rpm available
FLAG_USER_ONLY = "USER_ONLY"    # only user maxspeed available
FLAG_NEED_DATA = "NEED_DATA"    # no rpm source at all -> profile invalid

# pole_pairs_state values
PP_DRIVE = "DRIVE"              # CA[19] readable
PP_USER = "USER"                # CA[19] unreadable, user supplied the value
PP_NEED_DATA = "NEED_DATA"      # neither -> profile invalid (NO fallback 16)

RATED_RPM_DEV_MAX = 0.05        # 5 % relative deviation threshold (base = min)

# ---- P3 signature-band contract (docs/physics-gates-spec.md §2/§6.1) --------
# band = [alpha, beta] x i_ba_ref; yellow_lo/red_hi are the outer verdict
# boundaries consumed by physics_gates.sig_band().  GREEN-run-only updates:
# i_ba_history keeps the last IBA_HISTORY_MAX GREEN latches, i_ba_ref is the
# median of the last IBA_REF_RECENT of them.
SIG_ALPHA = 0.5
SIG_BETA = 1.5
SIG_YELLOW_LO = 0.3
SIG_RED_HI = 2.0
IBA_HISTORY_MAX = 8
IBA_REF_RECENT = 5

_PROFILE_SUBDIR = "motor_profiles"
_DEFAULT_SNAPSHOT_DIR = os.path.join(".omc", "state")


# ---------------------------------------------------------------- helpers

def _num(value: Any) -> Optional[float]:
    """Parse a drive/user numeric field.  None / garbage / non-finite -> None."""
    if value is None or isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):  # NaN / inf
        return None
    return f


def _pos(value: Any) -> Optional[float]:
    """Positive finite number or None."""
    f = _num(value)
    return f if (f is not None and f > 0.0) else None


def _int_exact(value: Any) -> Optional[int]:
    """Integer-valued field (e.g. CA[19]=21.0 -> 21).  21.5 / '??' -> None."""
    f = _num(value)
    if f is None or f != int(f):
        return None
    return int(f)


def _slug(name: str) -> str:
    """Filesystem-safe slug for the motor id (per-name JSON key)."""
    s = re.sub(r"[^0-9A-Za-z._-]+", "_", name.strip())
    s = s.strip("._")
    if not s:
        raise ValueError("motor profile name yields empty slug: %r" % (name,))
    return s


# ---------------------------------------------------------------- dataclass

@dataclass(frozen=True)
class MotorProfile:
    """불변 단일 진실원.  ``MotorProfile.from_sources()`` 로 생성한다."""

    name: str                                   # motor id (persistence key)
    schema: int = SCHEMA_VERSION

    # --- drive-read raw identity/limits -----------------------------------
    counts_per_rev: Optional[float] = None      # CA[18]  [counts/rev]
    motor_type: Optional[int] = None            # CA[28]  (raw enum)
    cont_current_a: Optional[float] = None      # CL[1]   [A, amplitude]
    peak_current_a: Optional[float] = None      # PL[1]   [A, amplitude]
    ts_s: Optional[float] = None                # TS      [s]
    vh2_counts_per_s: Optional[float] = None    # VH[2]   [counts/s]

    # --- pole pairs (NO fallback-16) --------------------------------------
    pole_pairs: Optional[int] = None
    pole_pairs_state: str = PP_NEED_DATA        # DRIVE | USER | NEED_DATA

    # --- rated rpm synthesis ----------------------------------------------
    rated_rpm_drive: Optional[float] = None     # VH[2]*60/CA[18]  [rpm]
    rated_rpm_user: Optional[float] = None      # Motor Settings maxspeed [rpm]
    effective_rated_rpm: Optional[float] = None  # min(available)  [rpm]
    rated_rpm_flag: str = FLAG_NEED_DATA

    # --- P2+ per-motor history slots (교차오염 방지 — 이번 단계는 자리만) --
    ka_baseline: Optional[float] = None         # [A/(rad/s^2)]-class, P2 채움
    signature_band: Optional[Mapping[str, float]] = None  # e.g. i_ba band
    i_ba_history: Tuple[float, ...] = field(default_factory=tuple)

    # ------------------------------------------------------------ factory

    @classmethod
    def from_sources(cls,
                     name: str,
                     drive_readings: Optional[Mapping[str, Any]] = None,
                     user_settings: Optional[Mapping[str, Any]] = None,
                     ) -> "MotorProfile":
        """드라이브 리드 + 사용자 입력 합성.

        drive_readings 키: "VH[2]", "CA[18]", "CA[19]", "CA[28]",
                           "CL[1]", "PL[1]", "TS"  (TS 단위 = 초)
        user_settings 키:  "maxspeed" [rpm], "pole_pairs"
        판독불가/누락 값은 None 취급 (예외를 내지 않고 상태 플래그로 표현).
        """
        if not isinstance(name, str) or not name.strip():
            raise ValueError("motor profile requires a non-empty name")
        _slug(name)  # fail fast if the name cannot become a JSON key
        d = drive_readings or {}
        u = user_settings or {}

        ca18 = _pos(d.get("CA[18]"))
        vh2 = _pos(d.get("VH[2]"))
        ts = _pos(d.get("TS"))
        cl1 = _pos(d.get("CL[1]"))
        pl1 = _pos(d.get("PL[1]"))
        mtype = _int_exact(d.get("CA[28]"))

        # rated rpm, drive-derived:  [counts/s]*60/[counts/rev] = [rpm]
        rpm_drive = (vh2 * 60.0 / ca18) if (vh2 is not None and ca18 is not None) else None
        rpm_user = _pos(u.get("maxspeed"))

        if rpm_drive is not None and rpm_user is not None:
            effective = min(rpm_drive, rpm_user)          # fail-closed
            dev = abs(rpm_drive - rpm_user) / min(rpm_drive, rpm_user)
            flag = FLAG_YELLOW if dev > RATED_RPM_DEV_MAX else FLAG_GREEN
        elif rpm_drive is not None:
            effective, flag = rpm_drive, FLAG_DRIVE_ONLY
        elif rpm_user is not None:
            effective, flag = rpm_user, FLAG_USER_ONLY
        else:
            effective, flag = None, FLAG_NEED_DATA

        # pole pairs: CA[19] if readable; else user input; else NEED_DATA.
        pp_drive = _int_exact(d.get("CA[19]"))
        if pp_drive is not None and pp_drive >= 1:
            pp, pp_state = pp_drive, PP_DRIVE
        else:
            pp_user = _int_exact(u.get("pole_pairs"))
            if pp_user is not None and pp_user >= 1:
                pp, pp_state = pp_user, PP_USER
            else:
                pp, pp_state = None, PP_NEED_DATA          # NO fallback 16

        return cls(name=name.strip(),
                   counts_per_rev=ca18, motor_type=mtype,
                   cont_current_a=cl1, peak_current_a=pl1,
                   ts_s=ts, vh2_counts_per_s=vh2,
                   pole_pairs=pp, pole_pairs_state=pp_state,
                   rated_rpm_drive=rpm_drive, rated_rpm_user=rpm_user,
                   effective_rated_rpm=effective, rated_rpm_flag=flag)

    # ---------------------------------------------- P3 GREEN-run history fill

    def with_green_run(self,
                       i_ba_a: Optional[float] = None,
                       k_a: Optional[float] = None) -> "MotorProfile":
        """GREEN 런 종료시에만 호출 (oracle rule: YELLOW/RED 런은 재베이스라인
        금지 — 호출측이 게이팅한다).  새 불변 프로필을 반환한다:

          * ``i_ba_history``  <- append(i_ba_a), 최근 IBA_HISTORY_MAX개 유지
          * ``signature_band['i_ba_ref_a']`` <- 최근 IBA_REF_RECENT개 median
          * ``ka_baseline``   <- k_a (양수일 때만 갱신, 아니면 기존 유지)

        i_ba_a/k_a 는 각각 None이면 해당 필드를 건드리지 않는다.  영속은
        호출측이 save()로 수행한다 (원자적 저장 재사용).
        """
        hist = self.i_ba_history
        band = dict(self.signature_band) if self.signature_band else {}
        iba = _pos(i_ba_a)
        if iba is not None:
            hist = tuple(hist + (float(iba),))[-IBA_HISTORY_MAX:]
            recent = sorted(hist[-IBA_REF_RECENT:])
            n = len(recent)
            median = (recent[n // 2] if n % 2
                      else 0.5 * (recent[n // 2 - 1] + recent[n // 2]))
            band = {"i_ba_ref_a": float(median),
                    "alpha": SIG_ALPHA, "beta": SIG_BETA,
                    "yellow_lo": SIG_YELLOW_LO, "red_hi": SIG_RED_HI,
                    "n_green": len(hist)}
        ka = _pos(k_a)
        ka_new = float(ka) if ka is not None else self.ka_baseline
        return dataclasses.replace(
            self, i_ba_history=hist,
            signature_band=(band or None), ka_baseline=ka_new)

    # ------------------------------------------------------------ validity

    @property
    def is_valid(self) -> bool:
        """P2+ 입력으로 쓸 수 있는가 (fail-closed).

        극쌍 미확정(NEED_DATA)이거나 정격 rpm 소스가 하나도 없으면 무효.
        """
        return (self.pole_pairs_state != PP_NEED_DATA
                and self.pole_pairs is not None
                and self.effective_rated_rpm is not None)

    # ------------------------------------------------------- serialization

    def to_dict(self) -> dict:
        out = dataclasses.asdict(self)
        out["i_ba_history"] = list(self.i_ba_history)
        if self.signature_band is not None:
            out["signature_band"] = dict(self.signature_band)
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MotorProfile":
        if not isinstance(data, Mapping):
            raise ValueError("profile payload must be a mapping")
        known = {f.name for f in dataclasses.fields(cls)}
        kw = {k: v for k, v in data.items() if k in known}
        if "name" not in kw:
            raise ValueError("profile payload missing 'name'")
        hist = kw.get("i_ba_history") or ()
        kw["i_ba_history"] = tuple(float(x) for x in hist)
        if kw.get("signature_band") is not None:
            kw["signature_band"] = dict(kw["signature_band"])
        return cls(**kw)

    # ---------------------------------------------------------- persistence

    @staticmethod
    def path_for(name: str,
                 snapshot_dir: str = _DEFAULT_SNAPSHOT_DIR) -> str:
        return os.path.join(snapshot_dir, _PROFILE_SUBDIR,
                            _slug(name) + ".json")

    def save(self, snapshot_dir: str = _DEFAULT_SNAPSHOT_DIR) -> str:
        """개별 JSON로 원자적 저장 (temp + os.replace).  Returns the path."""
        path = self.path_for(self.name, snapshot_dir)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        payload = json.dumps(self.to_dict(), ensure_ascii=False, indent=2,
                             sort_keys=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path),
                                   prefix="._mp_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
        return path

    @classmethod
    def load(cls, name: str,
             snapshot_dir: str = _DEFAULT_SNAPSHOT_DIR) -> "MotorProfile":
        """이름 키로 로드.  없으면 FileNotFoundError (침묵 폴백 금지)."""
        path = cls.path_for(name, snapshot_dir)
        with open(path, "r", encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))


def list_profiles(snapshot_dir: str = _DEFAULT_SNAPSHOT_DIR) -> Tuple[str, ...]:
    """snapshot_dir 아래 저장된 프로필의 motor id 목록 (저장된 name 필드)."""
    root = os.path.join(snapshot_dir, _PROFILE_SUBDIR)
    if not os.path.isdir(root):
        return ()
    names = []
    for fn in sorted(os.listdir(root)):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(root, fn), "r", encoding="utf-8") as fh:
                names.append(str(json.load(fh)["name"]))
        except (OSError, ValueError, KeyError):
            continue  # corrupt entries are skipped, never guessed at
    return tuple(names)
