# SPEC: Phase 2 오토튠 — 커뮤테이션 검증 + 속도/위치 루프

fable-physics 설계 (2026-07-13). 구현: 신규 `autotune_velpos.py` + `tests/test_autotune_velpos.py`.
전송층·아키텍처(`_Ctx`/스냅숏/I1~I5 불변식/abort/`_resolve_signals`/RED-불사)는 Phase 1
`autotune_current.py` 이월. 근거: `docs/autotune-current-spec.md`, `docs/recording-api.md`,
`.omc/paf5-brief.md`(Phase 2 그라운딩·읽기전용 프로브).

## §0. 관습·기호
- v=속도(레코더 Velocity idx1, VX) [cnt/s], CA[18]=65536 cnt/rev.
- I=토크전류(Active Current idx10, TC 지령) [**A 진폭**]. EAS표시 rms=÷√2.
- **K_a ≡ dv̇/dI = Kt·CA[18]/(2π·J_tot)** [cnt/s²/A] — 핵심 식별상수. Kt·J 개별값 불요.
- B=점성마찰(전류등가) [A/(cnt/s)], I_c=쿨롱마찰 [A], D=K_a·B [1/s].
- 속도 PI: u=KP[2]·(e+2π·KI[2]·∫e). KP[2] A/(cnt/s), KI[2] **Hz(영점=2π·KI[2]**, U-P2 실기검증).
- 위치 P: v_cmd=KP[3]·(p_cmd−p). KP[3] [1/s]. KI[3] 없음.
- 운동식: **v̇ = K_a·I − D·v − C·sgn(v)** (D=K_a·B, C=K_a·I_c).
- 루프주기 TS=100µs(WS[28]=WS[55]=TS 실기확정).

## 실기 확정치 (오라클·프로브)
- **GS[2]=0**(스케줄링 없음 → KP[2..]/KI[2] 실효). **오라클 EAS: KP[2]=7.896e-5·KI[2]=10.7·KP[3]=85.2.**
- **FF[1]=1.726e-7 A/(cnt/s²)** (=1/K_a 지문), FF[2]=1. CA[7]=438·CA[17]=5(커뮤 설정됨).
- 전류루프: KP[1]=0.07177·KI[1]=812.939, 크로스오버362Hz·PM55.7°. 플랜트 R_pp0.139·L_pp41.6µH.
- CL[1]=21.213A·PL[1]=70.71·MC=140. VH[2]=3.93e6(3600rpm)·ER[2]=1e8·ER[3]=1e9·HL/LL=0·AC=DC=SD=1e6·VH[3]=VL[3]=0·TR=100/20/100/20.

## §1. 커뮤테이션 검증 (재정렬 금지 — 검증만)
1. 회전0 필수: CA[7]==438·CA[17]==5·GS[2]==0·CA[41..44] 스냅숏일치. 다르면 RED "커뮤 변경감지"(CS/CA[7] 쓰기 절대금지).
2. 옵션 회전검증(§2 방법B 병합): JV±300rpm 정상상태 sign(v)==sign(JV) & |I_ss| 양방향 ≤0.10·CL[1]=2.12A & 비대칭≤×2. 위반→RED.
3. 방법A 펄스 중 즉시게이트: sign(v̇)≠sign(TC) 40ms내→abort+RED.

## §2. 기계 플랜트 식별
**시상수 분리**(통과): 전류 폐루프 362Hz(τ_i 0.7ms) vs 식별대역 ≤20Hz → ≥100× 분리, 전류루프=단위이득 취급.
### 방법 A(주력): UM=5 개루프 토크 ±펄스 → K_a
정지 record시작 → 50ms → TC=+I0 (Tp) → TC=−I0 (Tp) → TC=0 → fetch.
- **K_a=(v̇₊−v̇₋)/(Ī₊+|Ī₋|)** [분모=기록 실전류]. 같은 속도대 v* 창 매칭, ±상쇄로 마찰제거.
- v̇=창내 v(t) 최소자승 직선기울기(점차분 금지—양자화노이즈).
- 전역회귀: v̇(t)를 [I,v,sgn(v)]에 회귀 → K_a·B·I_c. 차분식과 ≤15%(G1a).
- v̇ 제2경로: Position(idx2) 창별 2차피팅 2a₂ vs 속도기울기 ≤10%(G1c). **∫v·dt vs ΔPos ≤5%(G1d—dt 검증, K_a는 dt 1차민감)**.
- 런2회(+먼저/−먼저) K_a ≤10%(G1b). 코깅: 800rpm f_e=213Hz, 60ms창=6.4주기→평균소거.
### 방법 B(마찰주력): 폐루프 JV 정상상태
JV∈{±327680,±983040}(±300/±900rpm) 각 도달0.8s→0.5s기록 Ī_ss. **I_ss=B·v+I_c·sgn(v)** 방향별 직선피팅→B·I_c. 방법A와 ≤30%(G1e, 이 값 최종채택). 기존 EAS게인 보호(ST 사용가능), §1-2 커뮤검증 겸함.
### 방법 C(SE): 채택 안 함(Stop Manager 우회·소켓거동 미확정·쿨롱 비선형).
### 안전 사이징(K_a*=5.79e6 기준)
프로브 I=0.25A·T=50ms(66rpm 무해). 본펄스 I0=0.10·CL[1]=2.12A(상한 0.2·CL[1]). **Tp=clip(cnt(800rpm)/(K_a_probe·I0),0.05,0.3)**(프로브 실측K_a로 사이징). 총회전≈0.95rev/런. SW가드 VX폴30ms |VX|>1.31e6(1200rpm)→abort.

## §3. PI 설계식 — EAS 역설계
**A1 [미확정-실기]**: FF[1]=1/K_a. K_a*=1/FF[1]=**5.794e6**.
1. ω_cv=KP[2]·K_a*=**457.5 rad/s**(72.8Hz). 2. β=ω_cv/(2π·KI[2])=**6.805**. 3. δ=ω_cv/KP[3]=**5.369**.
기각검사: 영점=기계극 가설이면 점성전류45.6A 비물리→**영점=크로스오버비율 규칙 확정**.
모델검산: 풀루프 속도 크로스오버73.9Hz·PM67.6°·GM15dB, 위치15Hz·PM81.1° = 건전.
```
ω_cv  = 0.04575 / TS_s            # 단일점 캘리브레이션(Phase1 0.2010 자매)
KP[2] = ω_cv / K_a_meas          # 유일한 측정의존 게인
KI[2] = ω_cv / (2π·6.805)        # TS=100µs→10.700Hz (결정론)
KP[3] = ω_cv / 5.369             # TS=100µs→85.20 (결정론)
FF[1]_advisory = 1/K_a_meas       # 결과표기만, 쓰기금지(기본)
```
**정직표기**: 0.04575·6.805·5.369는 이 드라이브 단일점 캘리브레이션. KI[2]·KP[3] 오라클일치는 구성상 자동(증거아님). **반증가능 검증=① K_a vs 1/FF[1] ±30%(A1) ② KP[2] 오라클 ±30% ③ PM게이트 ④ F2 스텝응답**.
**PM게이트**: 측정K_a·D로 L_v·L_p 수치평가(Phase1 loop_margins 재사용, H_ci=현 드라이브 KP[1]/KI[1]+R_pp/L_pp) → 속도PM≥50 & GM≥8dB & ω_cv·TS≤0.07 & 위치PM≥70 & ω_ci/ω_cv≥3 & ω_cv/KP[3]≥4. PM<50→ω_cv×0.8 재계산(최대3회, β·δ유지) 실패→RED.

## §4. 안전 절차·리밋 (기본리밋 신뢰금지)
- 사전(MO=0): 스냅숏JSON(I1, `.omc/state/autotune_vp_snapshot_<ts>.json`) → VH[2] 3600rpm 유지 → **SD=4e6** → HL[2]=+1.97e6/LL[2]=−1.97e6(±1800rpm, 쓰기+리드백, 거부=warnings만) → ER[2]=3.3e5 → VH[3]/VL[3]=0유지(다회전 필요) → ER[3] 무관.
- **운전자 게이트(필수)**: "축 자유회전·부하분리·예상회전 N rev" 다이얼로그 후 MO=1(allow_motion). SO==1 폴(2s).
- MO=1 전구간 가드(30ms): MF≠0 ∥ LC==1 ∥ |VX|>1.31e6 ∥ 세그먼트타임박스5s → abort. 전체120s.
- **Abort 체인**:
  - TC세그먼트: A1 TC=0 → A2 MO=0(코스트) → A3 리밋복원 → A4 RED. (ST 의존안함 U-P6.)
  - JV세그먼트: A1 JV=0;ST → A2 |VX|<cnt(30rpm)폴(2s,실패→즉시MO=0) → A3 MO=0 → A4 복원 → A5 RED.
  - 게인은 F1전까지 안씀→복원불요. SV는 F1동의후(I4). 통신실패1s×2재시도(I5), NaN즉시abort.

## §5. GREEN 게이트
- **G0 구성**: GS[2]==0·WS[28]==WS[55]==TS·UM==5·MF==0·CA[17]==5·CA[7]==438. 실패→RED(회전전).
- **G1 자기일관**: (a)K_a 차분vs회귀≤15%RED (b)런2회≤10%RED (c)속도vs위치2차≤10%YELLOW (d)∫v vs ΔPos≤5%RED (e)창피팅R²≥0.98YELLOW (f)A-B마찰≤30%YELLOW.
- **G2 물리성**: K_a∈[3e5,3e8]·B≥0·I_c≥0·마찰비≤0.5·JV무부하전류≤0.10·CL[1]. RED(부호/범위)/YELLOW(마찰비→I0증액1회).
- **G3 오라클**: K_a vs5.794e6 ±30%(A1)·KP[2] vs7.896e-5 ±30%·KI[2]=10.70±2%·KP[3]=85.2±2%(뒤둘 구성확인). 실패→YELLOW "FF[1]가정 반증 또는 관성변경".
- **G4 안정도**: §3 PM게이트 6항. 실패(감축3회)→RED.
- **G5 검증런(실기 F2)**: 새게인 JV스텝300rpm 오버슛≤15%·±5%정착≤60ms·잔진동없음·idx8추종. 실패→원게인복원+RED.
GREEN=G0~G4(+F2시 G5). F2 미실시=정직스텁 표기(Phase1 E4 패턴).

## §6. 의사코드 (P0~F)
**인프라 선행(fable-driver)**: `elmo_link.record()`를 `record_start(sig,len,tres)`+`record_fetch(timeout)`로 분리(기존 record=래퍼, 기존 테스트 불변). 이유: 기록중 TC/JV/VX 폴 필요(레코더 자율구동).
```
P0 assert is_connected; MO==0 (MO=1→RED, 자동disable금지)
P1 read TS,UM,MF,SR,GS[0..2],KP[1..3],KI[1..2],CA[7,17,18,41..44],CL[1],PL[1],MC,
       VH[2..3],VL[3],ER[2..3],HL[2..3],LL[2..3],AC,DC,SD,SP,FF[1..2],VX,PX,BV
P2 G0 (GS[2]≠0→RED "게인스케줄링 활성")
P3 snapshot JSON (I1)
P4 resolve signals: Velocity(^velocity(?!.*command)) · Active Current · Position(^position(?!.*(command|error))) · Velocity Command. 실패→RED+덤프
P5 리밋: SD=4e6; HL[2]=1.97e6; LL[2]=-1.97e6(쓰기+리드백,거부=warn); ER[2]=3.3e5
B0 [운전자게이트] MO=1(allow_motion); poll SO==1(2s)
B1 프로브: record_start(3sig,dt400µs,0.4s)→TC=+0.25(50ms)→TC=0→fetch → K_a_probe=v̇/Ī(부호게이트); v̇≈0→I×2 1회→RED "정지마찰과대"
B2 Tp=clip(cnt(800rpm)/(K_a_probe·I0),0.05,0.3); 회전예상표시
C1 런1: record_start(≥(2Tp+0.4)/400µs)→50ms→TC=+I0(Tp)→TC=−I0(Tp)→TC=0→fetch; VX/MF/LC 30ms가드
C2 런2(−I0먼저); §2.2 창선정→K_a_diff·회귀(K_a,B,I_c)·위치2차·∫v검증
D1 JV: JV=+327680→0.8s→record0.5s→Ī_ss; 반복{+983040,−327680,−983040}→JV=0;ST;|VX|<cnt(30)폴 → B·I_c확정+커뮤검증
E1 MO=0; 리밋복원(SD,HL[2],LL[2],ER[2])
E2 §3 설계(KP[2],KI[2],KP[3],FF[1]_adv)+G1~G4→status·evidence 반환
F1 [사용자 적용] MO==0확인→KP[2]=;KI[2]=;KP[3]=→(선택)SV  ※FF[1] 기본미변경
F2 [사용자 검증런] B0재통과→JV스텝cnt(300rpm)기록→G5; 실패=원게인복원+RED
```
엣지: 세그먼트간 TC=0 선행후 JV. 기록길이한계→TimeResolution=8 폴백.

## §7. 오라클/검산
**T1 실기**: K_a=5.79e6±30%[1/FF[1]] · KP[2]=7.90e-5±30% · KI[2]=10.70±2% · KP[3]=85.2±2% · 속도PM67.6°·크로스73.9Hz. B·I_c 오라클없음(신규, I_c 0.05~0.5A 추정).
**T3 시뮬(하드웨어불요)**: 이산 기계플랜트 v[k+1]=v[k]+dt(K_a·I−D·v−C·sgn v)+양자화노이즈, 전류루프=362Hz1차+1샘플지연, 진리K_a=5.79e6·B=1e-7·I_c=0.2A. 합격 K_a≤2%·B≤15%·I_c≤15%·KP[2]≤3%·KI[2]/KP[3]≤0.5%. **회귀이빨**: ±상쇄없는 단측K_a가 15~30%편향(Phase1 나이브 자매).
**T4 게이트**: EAS게인+K_a* → PM67.6°±1·GM15dB±0.5·위치PM81.1°±1.

## §8. 미확정 (실기 후 갱신)
U-P1 FF[1]=1/K_a(A1, K_a실측±30%로 확증). U-P2 속도PI 영점=2πKI(F2스텝). U-P3 KP[3]단위(F2). U-P4 HL[2]/LL[2]쓰기(리드백,실패해도SW가드). U-P5 record dt(G1d 흡수). U-P6 UM=5 TC모드 ST거동(abort는 ST의존안함). U-P7 Velocity 내부필터(기울기무영향, F2최종판정).

## §9. 개정 (2026-07-13, fable-physics) — B1.5 UNIT-DIAG + 원안복원
실기 1회차: k_a_probe≈46,000 = EAS암시 5.79e6의 1/125. **감속기(1:30 유성)는 EAS 튜닝 때도 장착 → EAS FF[1]·게인=loaded값 → K_a_true≈5.79e6 확정, 125배=우리 측정오차**(추가관성 아님). 오라클·설계규칙·§2.5 사이징 **원안 복원**(무거운관성 개정 철회).

**125배 판별**: (b)dt단독 배제(방향논증: dt_true=400µs/125=3.2µs<TS 불가; dt 최대오차는 ×1/4=TR4가정vs실TS). (a)속도채널 스케일 최유력(Velocity idx1=Phase1 미검증 유일채널, 내부단위 스케일 의심). 단 두 프로브 v̇ 전류무관 동일(11575/11510)=프로브창 오염(정지마찰/토크미인가) → 확정불가, 진단런 필요.

**B1.5 UNIT-DIAG (본펄스 전 하드게이트, 프로브 B1을 이 뒤로 이동)**:
- 진단런: TC=+0.5A 80ms→TC=0. 기록 **TR=1(dt=TS=100µs, Phase1 검증)**, 0.4s, 4채널 **[Position idx2·Velocity idx1·Active Current idx10·Current Command idx6]** + VX 30ms 폴로그(t_host,VX). 안전: K_a 3×에도 636rpm<1200, 출력 ≤1.7°.
- 판별식(원배열+수치 evidence 의무):
  - ① g(dt): 펄스구간={I_active>0.25A}, g=T_host(80ms)/(N_pulse·dt_가정). |g−1|>10%→dt_true=g·dt_가정.
  - ② s(속도스케일): s=ΔPosition/Σ(v[k]·g·dt_가정). 제2경로 s₂=median(VX_poll/v_rec 동시각).
  - ③ K_a(채널불문): 후반창 t∈[24,80]ms Position 2차피팅 ½v̇t² → K_a=v̇/Ī_active (**Velocity 안씀=최종심판**).
- 판정표: ΔP≈수천cnt&s≈1/125→**속도스케일**(v_rec×s 보정 or 속도=Position미분, K_a 5.79e6확증). ΔP≈수천&s≈1&g≈1/4→**dt**(dt_true=g·dt). **ΔP도 ~125배작음(수십cnt)&s≈1→단위정상·물리이상**: I_active≪I_cmd→**토크미인가**(UM=5 TC경로·MO/SR/MF/LC 로그), I_active≈I_cmd→기계구속/정지마찰(브레이크어웨이 램프진단). 복합→①→②순차.
- 하드게이트: 보정후 |s−1|≤5% & |g−1|≤10% & ③K_a가 ①②보정 속도기울기와 ≤10% → 통과시만 본펄스. (G1d 흡수·선행화.)

**기타 개정**: 매칭창 n1=0 방지→절대속도 아닌 **실측 v_pk [30%,70%] 상대구간**+v_pk<30rpm시 "모션부족" RED(적응 I0×2 1회≤0.4CL[1]). Current Command idx6 전기록 포함. evidence 원배열 의무(요약만 금지). 신규 U-P9=Velocity 단위, U-P10=UM=5 TC 실효.
**범용화(사용자 요구)**: 알고리즘=파라미터구동 범용(맨모터~감속기 실측 K_a로). EAS=이 드라이브 검증 advisory. 적응사이징·단위정확·검증(자기일관+F2)이 범용성 담보. 실기검증=이 감속기시스템(필드홀드아웃).
