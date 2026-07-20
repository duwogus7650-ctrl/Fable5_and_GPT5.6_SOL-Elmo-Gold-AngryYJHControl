# P4 SPEC — 백래시 내성 커뮤테이션 자립 ID (전원 재인가 → EAS 없이 서명 GREEN)

> fable-physics 2026-07-21. 구현자 = fable-driver(오프라인 시뮬 먼저), 실기는 감독 하 내일.
> 그라운딩: `docs/commutation-id-grounding.md`(P0+Admin PDF), `.omc/paf5-brief.md`(서명 RED 진단),
> `tasks/failure-ledger.md`(2026-07-15 δ 재추첨). 대상 모터 = 기어드 16극쌍(사용자 확정).

## 0. 기호·관습
- **δ** = 드라이브 가정 전기각 − 실제 로터 전기각. 부호: 가정이 앞선 방향을 +로 잠정. CA[7] tick 부호관계 s는 실기 확인.
- p=16(CA[19] 실독 일치). CA[7]: 정수 −512..512, **1 tick = 0.703125° elec**. CA[18]=65536, 전기1회전=4096cnt.
- CS: UM=3 전용·RAM·즉시. PA(UM=3): 512tick=1전기회전, BG로 발효. 전류=진폭 관습(√2 무개입), CL[1]=21.2132A.
- **지배 물리**: UM=5 토크/암페어 = cos δ배 붕괴, UM=3 스테퍼는 δ무관 정토크. cos δ<0이면 UM=5 홀드=양귀환(불안정).
- **모델 교차검증**: 원장 i_ba 0.887→4.05(비 4.566)·방향반전 ⟹ |δ|=acos(1/4.566)=102.7° vs 관측 103°(0.3° 일치).

## 1. 커뮤 미확립 enable 문제 (MF=0x80 idle)
**원인**: CA[17]=5 MO=1은 CA[7]+EnDat 무모션 재계산만. δ 나쁘면 나쁜 채 계산. UM=5 idle 홀드강성 ∝ Kt·cos δ. **cos δ<0 → 음강성 양귀환 → 위치발산 → MF=0x80(speed tracking, Admin p85) → 셧**. 오늘 idle 셧과 정합.
**따름정리(판별도구)**: MO=1 idle MF=0x80 ⟺ cos δ<0. cos δ와 cos(δ−180°)는 동시 음 불가 → **CA[7] 256tick(=180°) 플립하면 반드시 안정 반평면**. 두 번 다 폴트면 δ 원인 아님(배선/엔코더/부하).
**후보 순서**: 주=**A + 180°플립 프리앰블**(플립이 무모션·무측정으로 A의 약점 해소, A만 SV 비휘발), 2순위=B(CS, 매전원 폴백, UM3→5 생존 미확정), 최후=C(내장서치, EC36 미확정·CA[17]→5 리셋모순, `allow_candidate_c=False` 기본).

## 2. δ 실측 (백래시 내성)
순서: ①서명 램프(HOLD-CONFIRM) → ②K_a비 → ③UM3 expect-slip(판별) → ④(잔차>25°만)쿼드러처.
- **① 서명 램프**(`_breakaway_ramp`, cap 1.30A): +TC 단방향+HOLD-CONFIRM(유격통과 vs 진짜이탈) = 대칭이동 전제 없음. 산출 i_ba_meas·direction. `c_iba = clip(i_ba_ref/i_ba_meas,0,1)`, quality=LOW. cap 무이탈이면 상계만.
- **② K_a**(quality HIGH, 최종): 진단펄스(±상쇄)로 |K_a| → `c_ka = clip(|K_a|/K_a_healthy,0,1)`. 원장 지문: 토크/암페어는 cos δ붕괴하나 가속도-마찰 불변 → K_a비 마찰오염 없음.
- **③ 부호합성**: `cosδ_signed = direction·c(c_ka 우선)`, `|δ̂|=acos(clip(·,−1,1))`, 부호는 §3 1스텝이 해소. quality HIGH/LOW/BRACKET(무이탈 [60,120]°→90°).
- **④ UM3 expect-slip**(`_um3_drag`, I_test=i_ba_meas/√2): 추종 ⟺ cos δ≤1/√2 ⟺ δ≥45°(오염 확정). 슬립 ⟺ δ작음(기계마찰 라우팅, 전류증액 금지). pa_effective=False → 정직 RED.
- **⑤ 쿼드러처(옵션)**: CA[7]+128(90°)에서 반복 → `δ̂=atan2(±c90, c0)` 4상한. 모션 2배라 기본 미사용.

**K_a비↔δ 경계**: ≥0.90→≤25.8° GREEN · 0.707–0.90→25.8–45° YELLOW · 0.5–0.707→45–60° RED보정필수(cos45° 문턱=P3 상수) · <0.5→>60° RED(KA_BASELINE_DROP_FRAC=0.5 정합).

## 3. CA[7] 갱신식
```
Δtick = round(δ̂_deg · 512/360)                 # 1tick=0.703°, 양자화≤0.36° 무시
CA[7]ₙ = wrap(CA[7]ₒ − s·Δtick), wrap(v)=((v+512)%1024)−512
```
- **s∈{+1,−1} = 실기 1스텝 확정(P0 §7#1)**: s=+1 적용→δ 재측정, |δ̂|줄면 +1 확정/늘면 −1(이 2회는 서로 다른 가설이라 재시도 캡 무관). 확정 후 코드 상수 `CA7_SIGN` 동결.
- 예: δ̂=103°→Δ=146. CA[7]=438,s=+1→wrap(292). 180°플립=wrap(438+256)=−330.
- **쓰기 규율**(원장 게인 준용): MO=0 게이트 → `CA[7]=<정수>` 평문정수만(범위 사전검증) → 즉시 되읽기 정수 완전일치(rtol 아님) → 불일치 차단·RED. SV는 §4 수렴 후 오퍼레이터 게이트만. 쓰기=커뮤 리셋이라 MO=1 재계산 경유.

## 4. 수렴 루프 (상태기계)
```
[S0 SNAPSHOT] CA[7]/16/17(=5게이트)/25, UM(=5), MF, CL[1], CA[18/19], 게인, 리밋 → JSON 백업.
[S1 ENABLE-WATCH] MO=1→SO=1 폴(2s)→ idle 감시 enable_watch_s=1.5s MF 폴(50ms): 0x80→FAULT, 타MF→OTHER, 무폴트→STABLE.
[S2 FLIP(1회)] S1=FAULT면 MO=0→CA[7]+=256(wrap)→S1 재시도. 2번째도 FAULT→UM3 드래그 판별→정직 RED "비-커뮤 원인"+원복.
[S3 MEASURE] 서명 램프(§2①②)→δ̂,quality. i_ba∈대역 ∧ dir+1 ∧ |δ̂|≤25.8°→S6.
[S4 CORRECT] §3 적용(첫회 s=+1)→MO=0 쓰기·되읽기→S1 재진입.
[S5 CAP] max_a_iters=2(s확정 부호재시도 별도, 총 enable≤4). 소진→allow_candidate_b면 B확립(§5)+서명: GREEN이면 status=YELLOW '세션한정(CS)', 아니면 RED. CA[7] 원본복원(best_ca7는 evidence만).
[S6 CLOSE] _do_abort("측정완료")→TC=0/MO=0/리밋복원 검증→GREEN. SV는 오퍼레이터 확인+전량 되읽기 후만.
abort: 기존 _do_abort(TC=0→MO=0→리밋→UM 복원) + CA[7]ₒ 복원 스텝(실패시 RED사유 병기).
```
신규 모듈 `commutation_id.py`(autotune_velpos 프리미티브 import):
```python
@dataclass
class CommutationIDParams:
    snapshot_dir: str; signature_cap_a=1.30; enable_watch_s=1.5; flip_ticks=256
    max_a_iters=2; ca7_sign: Optional[int]=None; i_ba_ref_a=None; ka_healthy=None
    allow_candidate_b=True; allow_candidate_c=False; um3_align_i_ladder=(2.0,4.24,6.0)
    progress_fn/cancel_fn/sleep_fn/clock_fn  # 기존 계약
@dataclass
class CommutationIDResult:
    status; reason; path_used  # A|A+flip|A+B|B|C
    delta_est_deg; delta_quality  # HIGH|LOW|BRACKET
    ca7_before; ca7_after; ca7_sign_resolved; evidence; warnings
def run_commutation_id(link, params)->CommutationIDResult
def _enable_watch(ctx)->str            # STABLE|FAULT_0x80|OTHER
def _ca7_write_verified(ctx, value:int)->None
def _delta_estimate(ctx, sig_evidence)->tuple[float,str]
def _um3_align_cs(ctx, i_ladder)->dict         # 후보 B
def _um3_expect_slip(ctx, i_test_a)->dict      # _um3_drag 전류 파라미터화
```

## 5. 후보 B (CS 앵커) + δ 재추첨 판별
**B 시퀀스**(CR p62, 앵커쌍 PA=384/CS=0로 단위 소거):
`MO=0→UM=3→MO=1→TC 램프 0→I_align(사다리 2→4.24→6A)→PA=384;BG(UM3 스텝스윕, 스텝≤반전기피치)→정착(_wait_rest)→CS=0(즉시)→TC=0→MO=0→UM=5복원→MO=1→S1→서명`.
- 백래시 내성: 단방향 당김+정착, 대칭판정 없음. 이동≤반전기피치 11.25°기계 < 유격 22.9°기계 → 정렬이 유격 안에서 끝남(위저드 죽인 문제 회피).
- 정렬잔차 δ_align≤asin(I_fric_eq/I_align): I=2A→≤14.5°, 4.24A→≤6.8°. 서명 게이트가 최종심판, YELLOW/RED면 사다리 다음단(≤3단).
- **실기 확인 2건**: (i) CS가 UM=5 복귀 후 생존(§7#3) — 실패 관측=복귀 후 서명 RED/MF재발→B는 "측정 부트스트랩"으로 강등·A 이관. (ii) CS 수용 UM=3 한정 여부.

**δ 재추첨 판별(§7#2)** (A가 GREEN+SV 후):
`E1: SV→전원off→30s→on→연결→서명only→기록. E2: 반복(표본2).`
판정: 2/2 GREEN→재추첨 없음(A 최종, B 비상폴백). 1회라도 RED→재추첨 실재→**매전원 부트=B확립+서명** 표준 승격(자동제안, 자동실행 금지). **매전원 서명 게이트 영구 유지**(17% 착지 전례).

## 6. 안전 (전류=프로필 파생)
- 서명 램프 cap 1.30A(SIGNATURE_CAP_ABS_MAX_A 불변). UM3 사다리 2→4.24(0.2CL)→6(0.4CL/√2)A, **8.49A(0.4CL)는 오퍼레이터 승인 전용**.
- UM3 홀드동손: 2A 0.42W·6A 3.8W·8.49A 7.5W((3/2)R_ph I², R_ph=0.0695Ω). 소손사가는 수십A급 — 본 시퀀스는 그 아래. UM3 시퀀스당 통전≤20s+시퀀스간 휴지≥통전, 스톨열가드 재사용.
- 무회전 확인 UM3 ~1.4rpm·출력≤1.7°. enable-watch 1.5s는 idle(지령없음, MF폴만). 무인 금지(MO=1·CA[7] 쓰기·SV = 감독+GUI 확인).

## 7. 오프라인 시뮬 (CommutGearLashSim(GearLashSim), 목=실기 의미론)
1. `delta_deg` 상태. UM=5 토크=Kt·I·cos δ, 방향=sign(cos δ). UM=3 δ무관.
2. **MF=0x80**: UM=5·MO=1 cos δ<0 → 홀드발산 → T_fault 내 MF=128 래치·SO=0·MO 드롭, 이후 err 58. **idle에서** 발생(램프 전).
3. CA[7] 쓰기: MO=1 거부, 정수만, 쓰기시 `delta_deg += s_sim·Δtick·360/512`. **s_sim은 생성자 파라미터(알고리즘 비공개)**.
4. CS: UM=3만 수용, `cs_survives_um_switch: bool` 파라미터(False면 UM=5 복귀시 δ 원복).
5. `power_cycle(reroll)`: True면 δ~{0,59,75,103,115}° 재추첨, TW RAM 소실 포함.
6. **목-갭 3형제**: PA는 BG에서만 발효, BG=프로파일러 경유, wall-clock 직렬 지연 advance() 부과.
7. 백래시·정지마찰·HOLD-CONFIRM은 GearLashSim 상속(lash 4500cnt, i_s_load 2.5A).

**수용 시나리오(pytest)**:
| # | 구성 | 기준 |
|---|---|---|
| S1 | δ₀=59°,s_sim=+1 | 플립없이 A 1회→GREEN, |δ|≤25.8° |
| S2 | δ₀=103° | FAULT→플립1→보정→GREEN, path='A+flip', enable≤4 |
| S3 | δ₀=75°,ca7_sign=None,s_sim=−1 | 1스텝이 s=−1 확정 후 GREEN |
| S4 | δ₀=103°,cs_survives=False,A봉쇄 | B시도→복귀상실 검출→정직 YELLOW/RED |
| S5 | reroll=True,A GREEN 후 power_cycle | 부트 서명 RED→B확립→GREEN, status=YELLOW '세션한정' |
| S6 | δ무관 MF=128 주입 | 플립2회 FAULT→UM3 라우팅→RED "비-커뮤", CA[7] 원복 |
| S7 | max_a_iters 소진 | 3회째 없음, CA[7] 원복, 정직 RED |
각 시나리오 abort 후 스냅숏 원복(UM5·MO0·TC0·리밋·CA[7]) 시뮬 단언.

## 8. 내일 실기 런북 (감독 하)
전제: EAS Disconnect, 출력축 프리무빙(정지마찰 깨고 완전정지), E-stop 준비, 무인 금지.
| 단계 | 행위 | GREEN | abort | 닫는 질의 |
|---|---|---|---|---|
| R0 | 읽기전용 스냅숏+JSON백업 | 판독·CA[17]=5·MF=0 | 판독실패 | — |
| R1 | 서명only 베이스라인(1.30A) | 결과무관(δ 증거) | 타폴트 | — |
| R2 | R1 FAULT면 플립 CA[7]+=256→서명 | enable통과+측정치 | 플립후도 FAULT→R4판별후 중지 | §1.1 실증 |
| R3 | δ̂→s=+1 1스텝→재측정→s확정→최종보정→서명 | i_ba∈대역·dir+1·|δ̂|≤25.8° | 2회실패→R4 | **§7#1 s** |
| R4 | (R3실패) B: UM3정렬(2→4.24→6A,각≤20s)→CS=0→UM5복원→서명 | 복귀후 GREEN=CS생존 | 3단소진/RED | **§7#3 CS생존** |
| R5 | (R3 GREEN) SV(되읽기후)→전원사이클×2→각 부트 서명only | 2/2 GREEN=A영구 / RED=재추첨→B표준 | — | **§7#2 재추첨** |
| R6 | 종결: 스냅숏저장·ka_baseline 갱신(GREEN만)·원장 | 리밋/UM/MO 복원 | — | — |
R2~R4 통전은 1.30A 또는 UM3 6A 이하. 8.49A 승인전용 캡은 오늘 미사용.

## 판정
plausible. 실기 확인 필요 3건: ① CA[7] 부호 s(R3), ② CS UM=5 생존(R4), ③ 전원 δ 재추첨(R5, 표본2).
핵심모델(토크∝cos δ, MF=0x80=cos δ<0 양귀환)은 i_ba비→|δ|=102.7° vs 103° 교차검증 그라운딩.
신규 매직넘버 없음(전부 P2/P3·CR·실측 파생). 부트스트랩 주의: ka_healthy GREEN 이력 없으면 §2 HIGH→LOW 강등, R3 첫 GREEN이 baseline 심음.
재사용: autotune_velpos.py `_breakaway_ramp`:1805·`_um3_drag`:1635·`_drag_route`:1754·서명종결:2619·`_wait_rest`:721·`_do_abort`:1316, tests GearLashSim:2050.
