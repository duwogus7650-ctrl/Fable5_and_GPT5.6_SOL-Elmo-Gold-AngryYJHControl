# P3 SPEC — 검증 오라클의 모터-불문 물리 게이트 (동결)

> fable-physics 2026-07-21. EAS 게인/FF[1] 대조를 물리 게이트로 대체. 핵심 발견:
> 기존 매직상수가 전부 모터-불문 공식 — UM3_DRAG=0.4·CL/√2(=6.0 정확), "토크효율
> 70%"=1/√2=cos45° 커뮤문턱, GUARD=rated/3(=1200), verify=[0.10,0.25]·rated,
> 서명대역=[0.5,1.5]·i_ba_ref. 드라이브-규칙 상수(0.2010/1.2705/2.0 = KI-TS 결속)는
> 모터-불문이라 존치. 모터-특정(R/L/K_a/i_ba/FF[1]/EAS게인)만 프로필 파생·상대화.

## 관습
- 전류 = 드라이브 진폭(=√2·Arms). CL[1]=cont_current_a, PL[1]=peak_current_a.
- R_pp/L_pp = 상간(phase-to-phase). Vbus = 레코더 실독(가정 금지).
- Elmo: KP[1]=V/A(pp), KI[1]=Hz, C(s)=KP·(s+2π·KI)/s. 커뮤 토크 T∝cos δ.
- 검산: KI = 2·1.2705·(0.2010/TS)/2π = 812.87 Hz는 TS만으로 나옴(모터 무관). 모터는 KP=ω_c·L_pp로만 진입.

## 1. 전류루프(Phase1) 게이트
- **1.1 PM(유지)**: GREEN PM≥45° · YELLOW 40≤PM<45("실기 스텝응답 확인") · RED <40°. (실측 R̂·L̂·TS 1.5TS 지연모델 수치계산 — 이미 모터불문.)
- **1.2 ω_c 대역**: RED ω_c·TS>0.25(지연위상 21.5° 초과) · GREEN ω_c·TS≥0.1373(=3×0.04575, 케스케이드 분리비3) · YELLOW 0.0703≤ω_c·TS<0.1373(속도루프 감축 여지로 회복 가능) · RED <0.0703(감축 소진, 케스케이드 위반).
- **1.3 루프게인 정합 ρ=|C·G| (G5 계승)**: max|dev| GREEN ≤0.15 · YELLOW 0.15~0.30 · RED >0.30.
- **1.4 R/L 상대화** (절대 백스톱 R∈[1mΩ,10Ω]·L∈[1µH,10mH] 밖=RED 존치):
  - (a) κ_R = R_pp·CL[1]/Vbus [무차원]: GREEN [0.005,0.35] · YELLOW [0.001,0.005)∪(0.35,0.7] · RED <0.001 또는 >0.7. (경계 1표본 — 실기확인필요)
  - (b) L 관측성 ω₂·L_pp/R_pp ≥0.2 (미달 YELLOW "L 관측성 부족").
  - (c) 제어노력 KP·CL[1]/Vbus = ω_c·L_pp·CL[1]/Vbus: GREEN ≤0.6 · YELLOW 0.6~1.5 · RED >1.5. (실기확인필요)
  - τ_e=L/R∈[0.05,50]ms는 advisory만.
- **1.5 POLE_PAIRS_FALLBACK=16 폐기** → profile.pole_pairs. NEED_DATA면 판정=NEED_DATA(런 거부, RED 아님). 극피치=CA[18]/(2·pole_pairs).

## 2. 서명 게이트(커뮤 건강) — 프로필 대역화
- **2.1 물리**: i_ba = T_s/(K_t·cos δ). 커뮤 나쁘면 i_ba가 1/cos δ배 상승(하락은 커뮤 원인 아님 → 비대칭). i_ba ≤ β·ref ⟺ δ ≤ acos(1/β).
- **2.2 대역** (ref = profile signature_band.i_ba_ref_a):
  - GREEN [0.5,1.5]×ref (β=1.5→δ≤48.2°; 마찰변동은 K_a 드롭 게이트가 판별)
  - YELLOW [0.3,0.5)×ref(유격 오래치 의심) ∪ (1.5,2.0]×ref(δ≤60° 미확정, K_a로 위임)
  - RED >2.0×ref(δ≥60°) 또는 <0.3×ref
  - 절대 플로어: i_ba < 0.02·CL[1] → YELLOW "거의 무토크 이동"
  - 재현: [0.5,1.5]×0.887=[0.444,1.331] vs 실기 [0.50,1.30] 일치.
- **2.3 첫 런(베이스라인 없음) 프로토콜**: 대역 게이트 OFF, 대신:
  1. 방향 게이트(+TC→+dpx, i_ba 래치시점 signed, 하드 RED).
  2. UM3 드래그 expect-slip: I_test = i_ba_meas/√2 저속 스윕. 슬립=cos δ>1/√2=δ<45° 건강(회전 없음=안전), 따라감=δ≥45° 의심 RED. follow_ratio≥0.9=follow, ≤0.5=slip, 사이=YELLOW(백래시 오염 가능).
  3. 잠정 GREEN = 방향OK ∧ expect-slip=slip ∧ K_a>0 ∧ ka_dev통과 → 베이스라인 확립(i_ba_ref=i_ba, ka_baseline=K_a 프로필에).
  4. 이후: 대역 적용. 갱신=GREEN 런만 i_ba_history(최근8) append, i_ba_ref=최근5 GREEN median. YELLOW/RED 재베이스라인 금지.
- **2.4 K_a 드롭(프로필별 존치)**: K_a<0.5×ka_baseline → RED(δ≥60°). 저장을 단일파일→프로필 필드로 이동(교차오염 수리). YELLOW [0.5,0.7)×baseline.

## 3. UM3_DRAG — CL[1] 분율 파생
고정 6.0 폐기. **I_drag = i_cap/√2** (i_cap=적용 램프캡=ramp_frac·CL[1]). UM5에서 i_cap 못깼는데 UM3 I_drag에 따라감=cos δ<1/√2=δ>45° 커뮤결함("토크효율<70%" 정체), 슬립=진짜 기계마찰("기계 정지마찰 등가전류 > %.1fA"). 라우팅 게이트: i_cap ≥ 0.354·CL[1](=0.25·√2). 재현: 0.4×21.2132/√2=6.0000 정확. 분율후보 0.30·CL도 가능하나 판별각 흔들려 i_cap/√2 권고(45° 불변).

## 4. Phase2(속도/위치)
- **4.1 G3 해체**: ka_vs_1/ff1·kp2_vs_drive(±30%) → advisory 강등(RED 승격 금지). cfg(±2%, 쓰기-되읽기 무결)는 게이트 존치.
- **4.2 대체 게이트**:
  1. ∫v·dt vs ΔPos: dev GREEN ≤0.05 · YELLOW 0.05~0.10 · RED >0.10.
  2. K_a 내부일관성(다경로 ka_dev + 2차피팅 + K_a>0 하드) — 존치.
  3. 루프 여유 G4: PM_v≥50° ∧ GM≥8dB ∧ ω_cv·TS≤0.07 ∧ PM_p≥70° ∧ ω_ci/ω_cv≥3 ∧ ω_cv/KP[3]≥4 — 존치. 감축 3회 소진=RED.
  4. verify 정착: 오버슈트≤25% ∧ 오버스피드 0 ∧ 정착. 속도사다리 v₁=0.10·rated, v₂=0.25·rated(300→360 실기확인필요), 각 단≤0.6·GUARD.
  5. GUARD_RPM = clip(rated/3,150,3000)(=1200 재현). (실기확인필요)
  6. (신설 YELLOW-only advisory) 정상상태 마찰정합 |I_ss−(I_c+B·v)|≤max(0.15·I_ss, 노이즈).
- FF[1] advisory 밴드는 advisory 섹션으로 이동만.

## 5. EAS 대조 처리
게이트 경로(gates dict, RED/YELLOW 산정)에서 EAS 유래값(KP/KI/FF1 잔존, 0.0712/812.9 리터럴) 전면 제거. 신설 advisory dict: 드라이브 잔존 게인 대비 편차 표시만. UI 라벨: "참조(비게이트) — 드라이브 잔존 게인 대비, 비-EAS 튜닝 모터에선 미신뢰".

## 6. 구현 계약 (fable-driver)
### 6.1 프로필 스키마 (motor_profile.py 슬롯 이미 존재 — 채우는 로직만)
```python
signature_band = {"i_ba_ref_a": float, "alpha": 0.5, "beta": 1.5,
                  "yellow_lo": 0.3, "red_hi": 2.0, "n_green": int}
ka_baseline: float          # per-profile
i_ba_history: tuple[float]  # GREEN 런만 최근 8
```
프로필 갱신 = GREEN 런 종료시에만 원자적 save() 재사용.
### 6.2 신규 physics_gates.py (순수함수, I/O·드라이브 금지)
```python
@dataclass(frozen=True)
class GateVerdict:
    status: str   # GREEN|YELLOW|RED|NEED_DATA
    code: str     # P1_PM|P1_WC_BAND|P1_RHO|P1_R_REL|P1_L_REL|SIG_BAND|SIG_FIRST|KA_DROP|P2_G1D|P2_MARGINS|P2_VERIFY
    detail: dict  # 수치+단위+임계 evidence화
    advisory: bool = False

def p1_wc_band(wc_rad_s, ts_s)->GateVerdict          # §1.2
def p1_pm(pm_deg)->GateVerdict                        # §1.1
def p1_rho(rows)->GateVerdict                         # §1.3
def p1_r_relative(r_pp_ohm, cl1_a, vbus_v)->GateVerdict          # §1.4a
def p1_l_relative(l_pp_h, r_pp_ohm, wc_rad_s, f2_hz, cl1_a, vbus_v)->GateVerdict  # §1.4b,c
def sig_band(i_ba_a, profile)->GateVerdict            # §2.2; 베이스라인 없음→NEED_DATA
def sig_first_run(direction_ok, um3_follow_ratio, ka_ok)->GateVerdict  # §2.3
def ka_drop(k_a, profile)->GateVerdict                # §2.4
def derive_drag_current(cl1_a, i_cap_a=None, i_ba_meas_a=None)->tuple[float,dict]  # §3
def derive_guard_rpm(profile)->float                  # clip(rated/3,150,3000)
def derive_verify_speeds(profile, guard_rpm)->tuple   # (0.10,0.25)*rated, <=0.6*guard
def p2_g1d(dev)->GateVerdict                          # §4.2-1
def advisory_eas(drive_readings, results)->dict       # §5 — gates에 절대 미포함
def combine(verdicts)->str                            # worst-of; advisory 제외; NEED_DATA는 RED 아님(런 거부)
```
호출측: autotune_current.py G4/G5 조립(~:1645-1729)·폴백(:1303)이 소비. autotune_velpos.py 서명(:2540-2660)·드래그 라우터(:1755-)·G3(:2991-)·베이스라인(:1471-)이 소비. AutotuneVPParams.signature_i_min_a/max_a는 프로필 override 전용(기본 None=프로필 대역).

## 7. 다중모터 시뮬 검증
모터 매트릭스(SimDrive/VPSim 파라미터화, TS∈{50,100}µs):
| 케이스 | R_pp | L_pp | CL[1] | p | 특성 |
|---|---|---|---|---|---|
| A 이유닛 | 0.139Ω | 41.6µH | 21.2A | 16 | 회귀앵커 |
| B 코어리스 | 8Ω | 0.8mH | 1.4A | 4 | κ_R 상단 |
| C 중형서보 | 0.5Ω | 2.5mH | 8.5A | 5 | 고τ_e→ω_c 감축 YELLOW(정답, GREEN 비틀기 금지) |
| D 다이렉트 | 60mΩ | 25µH | 30A | 21 | L 관측성 하단 |
- 건강 런: 전 케이스 판정대로(C는 YELLOW 정답).
- 결함주입 정직 RED: δ=60°→서명대역 RED+K_a드롭 RED+첫런 expect-slip follow RED; dt×1.25→G1d RED; L̂×5→ρ RED; R를 κ_R>0.7→R_REL RED.
- 닭-달걀 E2E: 새 프로필 첫런 잠정경로(대역 미발동)→GREEN→i_ba_ref/ka_baseline 기록→2회차 대역 발동→YELLOW가 베이스라인 불변.
- 교차오염: 프로필 2개 교대 실행 시 서로 i_ba_ref/ka_baseline 불변.
- 리터럴 트립와이어: 게이트경로 소스에서 0.50/1.30/6.0/0.0712/812.9/POLE_PAIRS_FALLBACK 부재 grep(0.2010 등 드라이브규칙 상수 허용).

## 실기확인필요 라벨
κ_R·제어노력 경계(1표본), 첫런 follow_ratio 경계(백래시 오염), verify v₁ 300→360, GUARD 클립[150,3000], 신설 마찰정합 임계.

## 구현 정정 (2026-07-21, Opus 자체구현)
- **verify 속도 GUARD 캡 0.6→0.8**: SPEC §4.2-4의 "각 단≤0.6·GUARD"는 내부 모순.
  v2=0.25·rated이고 GUARD=rated/3이면 v2≡0.75·GUARD(항상)라 0.6 캡이 항상 발동해
  동결 실기값 900rpm(@GUARD 1200)을 720으로 깎음. 동결값이 진실이므로 캡을 0.8·GUARD로
  정정(0.75 통과 + 대형모터 GUARD 클립 3000 엣지 보호 유지). physics_gates.VERIFY_GUARD_FRAC=0.8.
- **구현 경위**: 위임 fable-driver(ac8bd5)가 6h 무출력 사일런트 데스 → Opus가 SPEC에서 직접
  구현. 1차 슬라이스 = physics_gates.py(순수함수 12종)+tests/test_physics_gates.py(25 passed).
  **autotune_current/velpos 배선은 미착수(프로덕션 회귀 위험 슬라이스, 별도 진행).**
