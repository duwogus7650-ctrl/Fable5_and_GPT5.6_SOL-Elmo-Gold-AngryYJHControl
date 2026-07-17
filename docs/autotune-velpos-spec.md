# SPEC: Phase 2 오토튠 — 커뮤테이션 검증 + 속도/위치 루프

fable-physics 설계 (2026-07-13). 구현: 신규 `autotune_velpos.py` + `tests/test_autotune_velpos.py`.
전송층·아키텍처(`_Ctx`/스냅숏/I1~I5 불변식/abort/`_resolve_signals`/RED-불사)는 Phase 1
`autotune_current.py` 이월. 근거: `docs/autotune-current-spec.md`, `docs/recording-api.md`,
`.omc/paf5-brief.md`(Phase 2 그라운딩·읽기전용 프로브).

## §0. 관습·기호
- v=속도(레코더 Velocity idx1, VX) [cnt/s]. `CA[18]=65536 cnt/rev`는 현재 EnDat 2.2 unit의
  관찰값일 뿐 runtime 기본값이 아니다. 매 실행에서 live finite positive `CA[18]`을 읽지 못하면 RED다.
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
- 현재 unit 참고값: KP[1]=0.07177·KI[1]=812.939, 크로스오버362Hz·PM55.7°,
  플랜트 R_pp0.139·L_pp41.6µH. 이 값들은 P2 runtime 폴백이 아니다. P2는 live finite positive
  `KP[1]/KI[1]`, 현재 connection generation의 커뮤테이션 서명 GREEN과 현재 P1 결과의 유효한 R/L을
  모두 요구하며 하나라도 없으면 drive write 전에 RED다.
- CL[1]=21.213A·PL[1]=70.71·MC=140. VH[2]=3.93e6(3600rpm)·ER[2]=1e8·ER[3]=1e9·HL/LL=0·AC=DC=SD=1e6·VH[3]=VL[3]=0·TR=100/20/100/20.

## §1. 커뮤테이션 검증 (재정렬 금지 — 검증만)
1. 회전0 필수: CA[17]==5·GS[2]==0·CA[41..44] 스냅숏일치. 다르면 RED "커뮤 변경감지"(CS/CA[7] 쓰기 절대금지). CA[7]=모터별 값 → 기록만(§5 G0 참조).
2. 옵션 회전검증(§2 방법B 병합): JV±300rpm 정상상태 sign(v)==sign(JV) & |I_ss| 양방향 ≤0.10·CL[1]=2.12A & 비대칭≤×2. 위반→RED.
3. 방법A 펄스 중 즉시게이트: sign(v̇)≠sign(TC) 40ms내→abort+RED.

### §1.1 독립 커뮤테이션 서명 게이트 (`signature_only`, 2026-07-15)

Phase 2 실행과 분리된 선행 안전 시험이다. `+TC`를 0→**절대 1.30A**로 최대 2.0s만
램프하고 HOLD-CONFIRM으로 지속 회전의 브레이크어웨이 전류와 부호를 판정한다.

- GREEN: `0.50 ≤ i_ba ≤ 1.30A`, `direction=+1`, 종료 되읽기 `TC=0`, `MO=0`, 임시 제한 전부 복귀.
- RED: 상한까지 미검출, 방향 음/불명, 전류창 이탈, 종료 상태 또는 제한 복귀 확인 실패.
- 격리 불변식: `UNIT-DIAG`, UM=3 드래그, 식별 펄스, `JV/BG`, 게인 Apply, `SV`에 진입하지 않는다.
- 설정 상한 `signature_cap_a>1.30A`, 잘못된 판정창, `ramp_time_s>2.0s`는 `MO=1` 전에 RED.
- 증거: `breakaway`, `signature_gate`, `final_state`, `abort/restored_limits`; GREEN뿐 아니라
  통전 후 미검출·역방향 RED도 abort 뒤 `MO`, `TC`, 임시 리밋을 되읽어 `final_state`에 남긴다.
  되읽기 실패는 서명 RED와 별도의 종료상태 실패로 사유에 병기한다. 결과 JSON은 기존
  `.omc/state/autotune_vp_result_*.json` 계보를 사용한다.

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
- 사전(MO=0): 스냅숏JSON(I1, `.omc/state/autotune_vp_snapshot_<ts>.json`) → VH[2] 3600rpm 유지 → **SD=4e6**, HL[2]=+1.97e6, LL[2]=−1.97e6, ER[2]=3.3e5를 적용한다. 네 assignment 뒤에는 서로 독립된 **full-set exact readback**을 수행하며, 쓰기 거부·timeout·비유한 응답·한 register라도 불일치하면 `MO=1` 전에 RED로 중단한다. VH[3]/VL[3]=0 유지(다회전 필요), ER[3]은 무관하다.
- `P2_LIMITS` WAL 원본과 되읽기는 원시 응답을 binary float로 바꾸기 전에 finite·integral·signed-32로
  판정한다. sub-ULP 소수는 정수로 반올림해 승인하지 않으며 WAL/assignment/enable 전에 RED다.
- **운전자 게이트(필수)**: "축 자유회전·부하분리·예상회전 N rev" 다이얼로그 후 MO=1(allow_motion). SO==1 폴(2s).
- MO=1 전구간 가드(30ms): MF≠0 ∥ LC==1 ∥ |VX|>1.31e6 ∥ 세그먼트타임박스5s → abort. 전체120s.
- **Abort 체인**:
  - TC세그먼트: A1 TC=0 → A2 MO=0(코스트) → A3 네 리밋 전체 원본 복원+full-set readback → A4 RED. 복원을 증명하지 못하면 `configuration_state=UNKNOWN`으로 잠근다. (ST 의존안함 U-P6.)
  - JV세그먼트: A1 JV=0;ST → A2 |VX|<cnt(30rpm)폴(2s,실패→즉시MO=0) → A3 MO=0 → A4 복원 → A5 RED.
  - 게인은 F1전까지 안씀→복원불요. Production F1/F3는 durable pre-assignment gain-trial WAL이
    없어 첫 drive I/O 전에 잠긴다. 아래 F1/F2 trial 복원 계약은 exact synthetic 회귀 또는 retained
    recovery 전용이며, 새 production trial이나 gain `SV` authority를 만들지 않는다.
    통신실패1s×2재시도(I5), NaN즉시abort.

## §5. GREEN 게이트
- **G0 구성**: GS[2]==0·WS[28]==WS[55]==TS·UM==5·MF==0·CA[17]==5. 실패→RED(회전전). **CA[7]은 모터별 커뮤값이라 값 게이트 아님**(다중모터 워크플로우, 2026-07-14): evidence 기록+정보성 emit만, expected_ca7 명시 시에만 opt-in 고정 게이트.
- **G1 자기일관**: (a)K_a 차분vs회귀≤15%RED (b)런2회≤10%RED (c)속도vs위치2차≤10%YELLOW (d)∫v vs ΔPos≤5%RED (e)창피팅R²≥0.98YELLOW (f)A-B마찰≤30%YELLOW.
- **G2 물리성**: K_a∈[3e5,3e8]·B≥0·I_c≥0·마찰비≤0.5·JV무부하전류≤0.10·CL[1]. RED(부호/범위)/YELLOW(마찰비→I0증액1회).
- **G3 오라클**: K_a vs5.794e6 ±30%(A1)·KP[2] vs7.896e-5 ±30%·KI[2]=10.70±2%·KP[3]=85.2±2%(뒤둘 구성확인). 실패→YELLOW "FF[1]가정 반증 또는 관성변경".
- **G4 안정도**: §3 PM게이트 6항. 실패(감축3회)→RED.
- **G5 installed-gain 검증런(실기 F2a)**: 현재 설치 게인의 JV스텝300rpm 오버슛≤15%·
  ±5%정착≤60ms·잔진동없음·idx8추종을 판정한다. 실패는 RED verdict이며 gain 변경·복원이나
  Apply/Save authority를 만들지 않는다. Synthetic/retained trial F2b만 별도 원게인 복원 계약을 가진다.
GREEN=G0~G4(+F2a/F2b 시 G5). F2 미실시=정직스텁 표기(Phase1 E4 패턴).

## §6. 의사코드 (P0~F)
**인프라 선행(fable-driver)**: `elmo_link.record()`를 `record_start(sig,len,tres)`+`record_fetch(timeout)`로 분리(기존 record=래퍼, 기존 테스트 불변). 이유: 기록중 TC/JV/VX 폴 필요(레코더 자율구동).
```
P0 assert is_connected; MO==0 (MO=1→RED, 자동disable금지)
P1 read TS,UM,MF,SR,GS[0..2],KP[1..3],KI[1..2],CA[7,17,18,41..44],CL[1],PL[1],MC,
       VH[2..3],VL[3],ER[2..3],HL[2..3],LL[2..3],AC,DC,SD,SP,FF[1..2],VX,PX,BV
P2 G0 (GS[2]≠0→RED "게인스케줄링 활성")
P3 snapshot JSON (I1)
P4 resolve signals: Velocity(^velocity(?!.*command)) · Active Current · Position(^position(?!.*(command|error))) · Velocity Command. 실패→RED+덤프
P5 리밋: SD=4e6; HL[2]=1.97e6; LL[2]=-1.97e6; ER[2]=3.3e5를 모두 쓴 뒤 full-set exact readback. 거부/timeout/silent mismatch/cross-register mismatch는 enable 전 RED.
B0 [운전자게이트] MO=1(allow_motion); poll SO==1(2s)
B1 프로브: record_start(3sig,dt400µs,0.4s)→TC=+0.25(50ms)→TC=0→fetch → K_a_probe=v̇/Ī(부호게이트); v̇≈0→I×2 1회→RED "정지마찰과대"
B2 Tp=clip(cnt(800rpm)/(K_a_probe·I0),0.05,0.3); 회전예상표시
C1 런1: record_start(≥(2Tp+0.4)/400µs)→50ms→TC=+I0(Tp)→TC=−I0(Tp)→TC=0→fetch; VX/MF/LC 30ms가드
C2 런2(−I0먼저); §2.2 창선정→K_a_diff·회귀(K_a,B,I_c)·위치2차·∫v검증
D1 JV: JV=+327680→0.8s→record0.5s→Ī_ss; 반복{+983040,−327680,−983040}→JV=0;ST;|VX|<cnt(30)폴 → B·I_c확정+커뮤검증
E1 MO=0; 리밋복원(SD,HL[2],LL[2],ER[2]) 뒤 full-set 원본 readback. 불확실하면 RED+`UNKNOWN`이며 worker가 이후 mutation과 commutation authority를 잠근다.
E2 §3 설계(KP[2],KI[2],KP[3],FF[1]_adv)+G1~G4→status·evidence 반환
F1 [production RAM 임시 적용 · LOCKED] hardware-capable link는 persistence query·snapshot·assignment
   전에 typed fail-closed한다. Synthetic-only 회귀 계약은 MO==0→원 KP[2]/KI[2]/KP[3] 스냅숏→
   새 3게인 쓰기+전항목 되읽기; 중간 실패=원게인 전항목 복원+되읽기, SV 금지. ※FF[1] 미변경
F2a [production "Verify Installed P2 on Motor"] B0와 current-generation commutation signature를
   재통과하고 `P2_LIMITS` WAL 아래 JV 스텝 cnt(300/900rpm)를 기록해 G5를 판정한다. 이 GREEN은
   현재 설치 게인의 verdict일 뿐 F1 trial이나 Apply/Save capability를 만들지 않는다.
F2b [synthetic/retained trial 검증] GREEN이면 시험값을 process-local로 유지하고,
   YELLOW/RED/Abort이면 원게인 전항목을 복원·되읽는다. Production Save authority는 없다.
F3 [production 별도 영구저장 · LOCKED] 새 gain trial을 crash-safe하게 증명할 durable pre-assignment
   WAL이 없으므로 UI/domain에서 잠긴다. Legacy/offline state-machine 회귀만 현재 3게인과 F1
   시험값의 일치 및 기존 persistence engine을 검사한다.
```
엣지: 세그먼트간 TC=0 선행후 JV. 기록길이한계→TimeResolution=8 폴백.

## §7. 오라클/검산
**T1 실기**: K_a=5.79e6±30%[1/FF[1]] · KP[2]=7.90e-5±30% · KI[2]=10.70±2% · KP[3]=85.2±2% · 속도PM67.6°·크로스73.9Hz. B·I_c 오라클없음(신규, I_c 0.05~0.5A 추정).
**T3 시뮬(하드웨어불요)**: 이산 기계플랜트 v[k+1]=v[k]+dt(K_a·I−D·v−C·sgn v)+양자화노이즈, 전류루프=362Hz1차+1샘플지연, 진리K_a=5.79e6·B=1e-7·I_c=0.2A. 합격 K_a≤2%·B≤15%·I_c≤15%·KP[2]≤3%·KI[2]/KP[3]≤0.5%. **회귀이빨**: ±상쇄없는 단측K_a가 15~30%편향(Phase1 나이브 자매).
**T4 게이트**: EAS게인+K_a* → PM67.6°±1·GM15dB±0.5·위치PM81.1°±1.

## §8. 미확정 (실기 후 갱신)
U-P1 FF[1]=1/K_a(A1, K_a실측±30%로 확증). U-P2 속도PI 영점=2πKI(F2스텝). U-P3 KP[3]단위(F2). U-P4 SD/HL[2]/LL[2]/ER[2] full-set apply/readback과 원본 복원을 fail-closed. U-P5 record dt(G1d 흡수). U-P6 UM=5 TC모드 ST거동(abort는 ST의존안함). U-P7 Velocity 내부필터(기울기무영향, F2최종판정).

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

## §10. 개정 2 (2026-07-13, fable-physics B1.5 실기판정 반영)
실기 진단런 판정: **125×는 단위오류 아님 — 속도스케일 s≈1 실측**; 46,000은 probe_i_a=0.5A가 감속기 정지마찰(T_s∈(0.061,0.25] N·m 모터측: 0.5A 무이동/2.12A 이동)을 못 넘어 stiction에 갇힌 저전류 노이즈. 실기 RED="기계구속"(정직, 그러나 축은 튜닝가능).

**B1.4 적응형 브레이크어웨이 램프 (UNIT-DIAG 앞 신설)**:
- TC 0→0.2·CL[1](=4.24A) ≤2s 램프, 30ms 폴. 검출=**폴 간 |ΔPX| 델타**>400cnt ∨ |VX|>3000cnt/s **2연속**(하드닝 #1: 누적 |PX−PX₀| 금지 — 백래시/컴플라이언스 와인드업은 단발 점프 후 포화라 누적검출은 영구 moved=True로 i_ba를 과소 래치; 진짜 브레이크어웨이=연속회전=연속 델타). 검출 즉시 TC=0, **i_ba 기록**(정지마찰 전류등가 상계 — B·I_c 식별 선험치로 evidence 보존, `jv.i_ba_prior_a` 교차참조·게이트 아님).
- **적응 probe = clip(1.5·i_ba, probe_i_a, 0.2·CL[1])** → UNIT-DIAG 펄스전류 i_diag=max(0.5A, probe)·B1 프로브전류에 사용 → 로터 실이동으로 위치기반 K_a 판별 성립.
- **캡 도달 무이동**: IQ 증인으로 분기 — IQ≈캡(토크 실인가)→정직 RED **"축 구속(클램프/브레이크?)"**; IQ≪캡→UNIT-DIAG 물리분기(토크미인가, MO/SR/MF/LC 로그)로 위임. 파라미터: ramp_frac=0.2·ramp_time_s≤2·poll_dt=0.03·detect_dpx=400·detect_vx=3000·breakaway_k=1.5.

**g 판별식 wall-clock 실측 (버그수정)**: poll_sleep이 30ms sleep마다 VX 직렬왕복(~15ms)을 끼워 실제 펄스가 명목 80ms→**~125ms(+56%)**. 舊 g=0.08/(N·dt)는 이를 dt계수 0.641로 오독. **수정: T_host를 TC 쓰기 전후 clock_fn(기본 time.monotonic) 브래킷 중점으로 실측**, g·후반창·g_corr 전부 실측 T_host 사용. 물리 하한 max(브래킷, 명목) — 벽시계는 요청 sleep 합보다 짧을 수 없으므로 하한은 clock이 sleep_fn과 이질적인(미주입 시뮬) 경우만 발동, `t_pulse_src`로 evidence 명시. 시뮬은 clock_fn=sim.t 주입.
- 안전 불변: MF/LC 가드 원강도·1200rpm 가드·abort 체인(TC=0→MO=0)·K_a/B/I_c 수식·게이트 G0~G4 불변. 안전규모(캡 4.24A까지 램프, 검출 즉시 탈전): 검출까지 회전 «1 rev.

**§10 하드닝(fable-critic 독립리뷰, 2026-07-13)**:
- **UNIT-DIAG 모션 조기종료(#2)**: 진단 펄스는 적응전류(≤0.2·CL[1])라 저동마찰 플랜트에서 80ms 내 1200rpm 가드 도달 가능(안전무해·런사망) → 펄스 폴 중 |VX|>500rpm이면 즉시 TC=0, 캡처된 창으로 g/s/K_a 판별(후반창 표본부족은 기존 정직 RED). 舊 "0.5A 고정→636rpm<1200" 안전산정은 적응전류+조기종료 기준으로 대체(`early_stop`·`t_pulse_nominal_s` evidence). 잔여 코스트 대비 각 TC 스테이지 앞 `_wait_rest`(|VX|<30rpm, 5s 한도, 실패→정직 abort).
- **IQ 판독불가 정직화(#3)**: 캡 무이동+IQ 비수치 → "IQ 토크 실인가 확인" 주장 금지, "IQ 판독불가" 경고와 함께 UNIT-DIAG 물리분기로 위임(기록 전류로 같은 판별 재유도).
- **전류채널 명시 RED(#4)**: 로터 이동(ΔPos≥200cnt)했는데 기록 Active Current가 0.5·i_diag 미달(n_pulse=0) → "전류채널 이상 의심" 명시 RED(舊 IndexError/ZeroDivision이 "내부 예외"로 뭉개지던 경로 제거).
- **t_pulse_src 양분기 고정(#5)**: measured(clock_fn)/nominal-floor 두 경로 모두 테스트로 검증(이질 clock=nominal-floor에서 g≈1·무보정).

**§11 개정 3 (2026-07-13, fable-physics 유격 오검출 판정 + 마무리 버그수리 2건)**:
- **RAMP→HOLD-CONFIRM**(§10 검출 위에 신설): 실기 i_ba=1.01A=유격통과 오검출(총이동 4166cnt=출력 0.76°, 진짜 부하 i_ba>1.52A). 물리 불변량=유격통과는 거리 유한(≤유격), 진짜 부하 이탈은 토크 유지 시 거리 무한. RAMP 검출 시 TC를 검출전류에 **동결**하고 확인창 최대 5폴: **지속**(검출 후 누적이동>6000cnt[유격상계 출력1.0°=5461 상회] ∨ |VX|>3000 3연속)→i_ba 래치; **실속**(2폴 연속 정온)→유격통과로 분류(`lash_events` 기록)·램프 재개. 캡 무지속→기존 IQ증인 경로. lash 이벤트>2회→"디텐트 래칫 의심" 경고. 파라미터 hold_window_polls=5·sustain_dpx_cnt=6000·sustain_vx_consec=3.
- **UNIT-DIAG 상향 사다리(이중방어)**: 무이동/유격착지 펄스 → i_diag ×1.5→×2.25→**캡(0.2·CL[1])** 최대 3회 상향 재펄스(각각 500rpm 조기종료 보호, 상향은 경고로 가시화). 성공=|ΔPos|>200cnt **그리고 후반 피팅창 모션 잔존**. 토크미인가/전류채널이상/표본부족/하드게이트는 종결 RED 유지. 캡에서도 무지속일 때만 최종 RED "축 구속/고마찰(기계구속)". 성공 상향전류는 B1 프로브 하한으로 피드포워드(상향으로 살린 축이 B1에서 죽는 모순 방지).
- **버그수리 1(유격착지 판별 분모)**: 잔존모션 비율의 분모를 레코드 전체 ΔPos → **토크 인가구간 내 이동(pulse_travel)**으로. 저동마찰 플랜트에서 조기종료 펄스(30ms) 후 코스트가 ΔPos를 지배(실측 157k cnt 중 ~150k=코스트)해 진짜 도는 로터가 "착지"로 오분류→false RED 나던 결함. 착지=인가구간 내 이동이 후반창에 없음, 코스트는 무관.
- **버그수리 2(정지 전제)**: 정지마찰은 **정지 출발 펄스**에만 게이팅 — |VX|<30rpm(=32768cnt/s, 폴당 1638cnt 이동)은 정지가 아님. `_wait_rest`=VX(<30rpm)+PX(폴 간 |ΔPX|<detect_dpx) **이중증인 2연속**으로 강화, 매 진단/상향/프로브/펄스런 앞 적용. (시뮬도 동일 물리로 정정: 쿨롱마찰 명시적분의 0교차 채터링 리밋사이클—로터가 영영 재점착 안 함—을 Karnopp 클램프로 제거.)
- **[HIGH] 본펄스 사이징 오더킬러 수리(fable-critic 확정)**: 舊 i0=0.1·CL[1] 고정은 기어드 정지마찰(2.5A) 미만 → 첫 본펄스 무이동 → 재시도 i0×2=4.24A인데 **tp 미재산정(71ms 유지)** → 가속 2.34e7cnt/s²로 **56ms에 1200rpm 가드 돌파** → 건강한 축 false RED(런 사망; 舊 수식 수기재현 일치). 수리 3중: ① **i0 = max(min(frac·CL[1], 0.2·CL[1]), 검증된 mover 전류)** — mover=UNIT-DIAG 최종 성공 펄스전류(로터 실이동 실증, `sizing.i_mover_a`), 첫 펄스부터 이동 ② **tp = clip(target/(K_a_probe·i0), 0.05, 0.3)를 i0 변경마다 재산정**(`_size_tp`, 모션부족 ×2·마찰비 ×1.5 재시도 포함) ③ **본펄스 모션 조기종료**(UNIT-DIAG 패턴 확장, `_pulse_sleep_with_cut`): 폴 중 |VX|>0.9·가드(1080rpm)면 즉시 다음 스텝으로 컷, 캡처창으로 분석 계속(경고 가시화, `pulse_early_stops` evidence) — 정상 사이징 펄스(TP_MIN 클립 최악 ~1071rpm)는 컷 미도달. 폴당 상승이 컷~가드 밴드(131k cnt/s)를 뛰어넘는 초고가속은 여전히 가드가 최종 방어(느린 초과=컷 생존 YELLOW / 빠른 초과=가드 RED, 양경로 테스트 고정). 검증 이빨=GearLashSim **기본 파라미터**로 GREEN(실측: i0=3.894A·tp=50ms·v_pk=955rpm=가드 여유 20%·K_a +0.04%).

## §12. 개정 4 (2026-07-13, fable-physics 캡 상향 + UM=3 판별실험)
실기 최종: **캡 0.2·CL(4.24A)에서도 무이탈 = i_ba>4.24A 확정**(브레이크 없음·출력축 자유). 마찰 가설은 건강 상한; **커뮤테이션 토크효율 저하 미배제(진지 후보)**.
**PART A — 캡 상향 0.4·CL + 재산정**:
- ramp_frac 기본 0.2 유지(맨모터), 이 유닛은 params로 0.4(=8.49A). **자동 램프 절대상한 0.4·CL**(P2 사전검증), 0.6·CL은 오퍼레이터 승인 전용 상수(RAMP_FRAC_OPERATOR_ONLY, 파라미터 경로 없음).
- **고전류 고속폴**: tc>2A 구간 VX 단독 10ms 폴(PX+VX 30ms쌍은 실주기 ~60ms→이탈 스냅이 2폴에 2700rpm). PX는 HOLD 확인단계에서 재앵커.
- **HOLD 즉시확정**: |VX|≥0.25·가드(300rpm)면 1폴 확정+TC=0(150ms 확인창에서 3300rpm까지 크는 구멍 봉쇄, 유격 자유비행으론 도달 불가 속도). 저속 이탈은 기존 지속판정 유지.
- **본펄스 상한 해제**: i0 = min(max(frac·CL, **1.25·i_ba**, mover), **0.4·CL**) — 0.2·CL 천장 폐기(i_ba>4.24 유닛은 2.12A 펄스로 측정 무의미). tp는 **순전류 i_net=i0−0.75·i_ba** 기반 사이징(하한 0.25·i0), **컷 0.9→0.75·가드/10ms VX폴**(B1 프로브에도 동일 컷 — 적응전류 프로브 50ms가 가드 넘던 구멍). UNIT-DIAG 캡도 ramp_frac 연동(0.4·CL), 펄스 폴 10ms 고속화, 후반창 시작 min(24ms, 0.4·t_pulse)(초고전류 조기종료 펄스의 빈 창 방지).
- **와인드업-전류 곡선**: 램프 중 1/2/4/6/8A 교차 시 ΔPX·IQ 기록(`windup_curve.points`; 탄성≈선형 모델 60·i cnt, IQ↑에 와인드업 포화=토크 메시 미도달=커뮤 적신호) + 램프 전구간 레코더 캡처(base 4채널 + personality에 있으면 Reactive Current/Field Angle, `windup_curve.rec`).
**PART B — UM=3 저속 드래그 판별(커뮤 무관 토크 오라클)**: 캡 무이탈+토크실인가일 때만 실행. MO=0→UM=3→MO=1, TC=6A 고정, PA(전기각 512tick/극쌍, CR :15742) ~1 elec rev/s로 각 방향 3 elec rev(모터 51°=출력 1.7°, 가드 무관). **추종률=|ΔPX|/(3·CA[18]/CA[19]), 양방향 min ≥0.9 판정**(`um3_drag` evidence: 지령각-PX 시계열).
- 라우팅(정직 RED, 전류 증액 금지): **추종≥0.9** → "기계는 ≤0.72N·m로 구동됨 — 커뮤테이션 토크효율<70% 의심, EAS 커뮤 재실행/CA[7] 확인". **슬립<0.9** → "진짜 기계 마찰 T_s>0.72N·m(출력 20+N·m), 기계 점검". CA[19] 판독불가 시 판별 생략+경고.
- 안전: UM은 정상경로(finally)와 abort 체인(A_um) **이중 복원**. 가드 1200rpm 최후방어 유지 — TC구간 과사이징은 10ms 컷이 소유(느린 초과=컷 생존), JV구간이 가드 이빨 테스트 경로.


## §13. 개정 5 (2026-07-13, fable-critic 독립리뷰 — PART B 거짓판정 위험 봉쇄)
- **[HIGH-2] UM=3 PA 스윕 실효성**: CR 대조 — PA는 Integer(:12471)·"Effective on the next call to BG"(:12476)·VH[3]/HL[3] 소프트리밋 대상(실기 전부 0!). 舊 코드는 float PA만 송신·BG 없음 → 스테이터각 정지 → 전 유닛 거짓 "기계 RED" 위험. 수리: **PA=int(round(·)) + 매 스텝 BG(즉시형이어도 무해)** + **초기 실효검사**(첫 방향 0.5 elec rev 시점 PX 응답 < 20%·기대(1560cnt)이면 `pa_effective=False` → **"판별 불가" 정직 RED** — 기계 단정 절대 금지: 죽은 스테이터각과 구속축은 헤드리스 구별 불가). 슬립 verdict 문구도 "슬립 **또는 PA 미실효**(실기 특성화 필요)"로. BG-PTP는 SP/AC/DC 프로파일러라 1 elec rev/s 미보장 — 실효검사가 안전망. evidence: `pa_effective`·`early_px_response_cnt`.
- **[HIGH-1] PART B 게이트**: 드래그 판별은 **i_cap ≥ 6A(UM3_DRAG_I_A)일 때만** 성립(미충족이면 드래그토크>캡토크라 항상 추종 → 건강한 기계마찰을 커뮤 RED로 오라우팅). `_drag_route` 게이트로 통합; 미충족/CA[19]불가/예외 시 일반 RED에 **"UM3 판별 유보"** 명시.
- **[MEDIUM] 폴 지연 가드밴드**: 실기 직렬지연(PX+VX쌍 ~60ms)에서 정상 사이징도 폴당 400~1100rpm 상승 → 컷(舊 0.75)~가드 밴드 붕괴. 수리: 펄스/HOLD/고속램프 창의 인슬립 가드 **MF/LC 생략(VX 단독, `guard_vx_only`)**, 모션컷 **0.75→0.6·가드(720rpm)**, **사이징 타깃을 0.8·컷(=576rpm)으로 클램프**(정상 펄스는 컷 미도달 보장), **검출 폴 시점 |VX|≥300rpm이면 HOLD 없이 즉시 래치+TC=0**(유격 자유비행은 2연속 검출 시점엔 종료 — 램프 자체 불변식). fire-safe: MF/LC는 다음 일반 창에서 재개, HL[2] 백스톱 유지.
- **[LOW-1]** B1 프로브 재시도 캡을 0.2·CL→PULSE_FRAC_ABS_MAX(0.4)·CL로 일관화 + 감액 금지(max 결합).
- **[LOW-2]** UNIT-DIAG 사다리 소진(무이동·토크실인가)도 PART B와 동일 전제 → 게이트 충족 시 `_drag_route` 경유, 미충족 시 "판별 유보" 표기(기계구속 단정 완화).
- 검증: 목이 실기 의미론 인코딩(**PA는 BG에서만 실효**) — 커뮤 라우팅 테스트가 BG 200회 실송신을 증명, BG무시 목→판별불가 RED, 부분슬립 목→정직 라벨 기계 RED, ×2 지연 목→컷이 가드 전 개입(v_pk 793rpm·K_a −0.09%), 기본캡 게이트 보류.


## §14. 개정 6 (2026-07-14, fable-physics 상향캡 실기판정 — 처방 1~3+5 구현, 4는 이월)
실기 판정: **i_ba=1.33A는 가짜**(백래시 자유비행+착지) — HOLD 속도 89k→68k→55k→6k **단조 붕괴**(구동 아닌 과도소산). s≈1·g≈1로 125× 단위설 최종기각, 81% 게이트는 정직. 문제=백래시 관통 K_a 식별.
- **처방1 [최우선] 지속판정 AND-재설계**: 舊 크기-단독(|VX|>3k 3연속)이 감쇠 과도를 통과·6000cnt 임계 부족(자유이동 외피 ≥8634 관측, 유닛따라 2k~9k). 新 **지속 = 누적 > max(13000cnt, 2×lash실측) AND vx_now ≥ 0.5×HOLD최대 vx**(붕괴 기각). **붕괴**(vx_now<0.5×max, 실모션 후)=즉시 실속 분류→`lash_events` 기록(collapsed·vx_max·vx_end 포함)→램프 재개. 확인창을 **15폴(450ms)로 연장하되 유망(비감쇠)일 때만** — 진짜 이탈은 이동 무한이라 임계 도달, 과도는 유격 유계라 불가(물리 불변량). 즉시확정(≥300rpm) 경로 유지. **소급검증: 실기 시계열 6k/89k=0.07 → 폴4 붕괴=실속(舊 규칙은 지속 오판 재현)**.
- **처방2 UNIT-DIAG 성공=지속회전**: 舊 "이동>200cnt"가 269cnt 꿈틀 통과. 新 성공 = **|late_travel| > max(200, 3×60·i_diag[와인드업 모델]) AND 펄스 말미 속도 > 3000cnt/s(POSITION 미분 — 속도채널은 진단 대상이라 게이트 금지)**. 미충족=`유격착지/꿈틀`로 escalation 계속(≤캡). escalation 펄스 10ms VX단독 폴(§13에서 기적용).
- **처방3 UM3 라우팅 교정**: 사다리 소진의 드래그 라우팅을 무이동 한정→**모든 소진 모드**(무이동·유격착지/꿈틀 = "지속회전 없음")로 — 실기 가짜모션이 드래그를 건너뛴 실버그. 램프 캡아웃 경로와 합쳐 "지속회전 없음"이면 (게이트 충족 시) 반드시 드래그.
- **처방5 부수**: escalation 각 레벨 (i, ΔPos)를 `windup_curve.points`에 다점 기록(src=unitdiag_escalation — 선형성=커뮤 건전성 동승검증). **K_a 절대 타당성 advisory**: FF[1] 존재 시 실측이 함의값의 [0.1×,10×] 밖이면 경고 명시(실기 1/640 즉시 포착용). G1d에 U-P5(tres=4 dt 상한) 폐색 주석.
- **처방4 [이월 — 다음 구간]**: 프리로드 바이어스(+1.5A급 0.5s, TC 0복귀 금지) + **단방향 2레벨 차분 K_a=(a_hi−a_lo)/(i_hi−i_lo)**(± 반전 폐기 — 반전마다 유격 재개방 2×lash 오염), B·I_c 동방향 2속 JV, −방향 1회는 비대칭 확인으로 강등. C1/C2·_analyze 코어 재작성이라 별도 구간 권장. **주의: 이번 실기에서 i_ba가 0.4·CL도 초과하면 본식별 미도달(드래그 판별 RED로 종료)이라 처방4는 그 다음 관문.**
- 검증: TransitDecaySim(실기 시계열 인코딩)→실속분류+진짜 i_ba=5.19 래치+K_a −0.01%; RiseJiggleSim(269cnt)→꿈틀 escalation·기본캡 소진 정직 RED; 상향캡 소진→드래그 실행("판별 불가")=라우팅 증명.


### §14.1 실기 전 보강 2건 (2026-07-14, fable-critic)
- **[#1] D1 JV 무부하전류 게이트 적응화**: 고정 0.10·CL(=2.12A)은 i_ba≥4.24A 실기확정 이전의 가정 — 기어드 운전마찰(B·v+I_c)이 300rpm에서 2.12A를 넘으면 K_a 식별을 다 마치고 D1에서 런 사망. 新 게이트 = **max(0.10·CL, 1.2·i_ba)** (i_ba=정지마찰 상계 ≥ 운전마찰 상계; 1.2는 B·v 여유). i_ba 부재 시 기존 폴백. `jv.i_ss_max_a` evidence. 검증: i_s=5/i_c=3 기어드 sim에서 I_ss 3.03~3.10A(舊 게이트 초과)로 D1 통과·I_c=3.00 정확·K_a −0.15%.
- **[#2] UNIT-DIAG 말미속도 최소자승화**: 舊 2점 0.8ms 차분은 위치노이즈 ±1.5cnt가 >3000cnt/s로 읽혀(4cnt/0.8ms=5000) **말기 착지**(travel 테스트는 통과하는 함정)를 지속회전으로 오통과시킬 수 있음 — 모듈 규율("slopes by least squares — never point differences") 위반이었음. 新 = **창 말미 ~10ms 최소자승 기울기**(`window_slope` 재사용, UNITDIAG_TAIL_S=0.010). 검증: 말기착지(+50ms, 400cnt)+±2cnt 노이즈 sim에서 LSQ 말미속도 6cnt/s → 꿈틀 기각·escalation(舊 최악치 5000cnt/s는 오통과 경계).
- **명시적 미변경**: MEDIUM-2(sustain 상수의 CA[18] 비례화 — 저해상도 엔코더 사각지대)와 처방4(프리로드+단방향 2레벨 K_a)는 이 유닛(CA[18]=65536)에서 안전하므로 다음 개정에서 함께(§14 이월 기록 유지).


### §14.2 방향 반전 안전보강 4건 (2026-07-14, fable-physics §3)
배경: 이 유닛=**유효-역방향 커뮤테이션**(배선 상순서 vs 엔코더 방향 반대 → +TC→−피드백, 전 관측 부호 일관 음). 수리는 사용자가 EAS에서 CA[25]=1+재커뮤. 코드는 반전을 더 일찍·정직하게:
- **보강1**: 방향 RED를 B1(:904)에서 **램프 i_ba 래치 시점**으로 — 래치 때 signed dpx(HOLD)/signed VX로 피드백 부호 판정, 음이면 **진단펄스 통전 전 조기중단**(실기는 unit-diag가 19,571cnt 역회전 후에야 사망). `breakaway.direction=±1`+`direction_basis` evidence.
- **보강2(심층방어)**: 실기에서 unit-diag 하드게이트가 **음의 K_a(ka_pos=−5.5e5)로 PASS**(ka_dev=크기 일관성만 검사) → `_unit_diag_pulse`에 **ka_pos>0 단언**(+펄스=+가속): 음이면 종결 방향 RED.
- **보강3**: 메시지 정정 — "커뮤 부호 이상"(오해: 커뮤는 유효함) → **"방향 반전(유효-역방향 커뮤테이션): +TC→−피드백. 수리: MO=0→CA[25]=1→재커뮤테이션→SV"**(램프/diag/B1 3층 공통, DIR_FIX_MSG). **묵시적 부호보정 금지 명문화**(반전 상태 게인 적용=폭주).
- **보강4**: `design_vp_gains`에 **K_a>0 입력 단언**(ValueError) — 음의 K_a가 ω/K_a→음의 KP[2]로 유입되는 이중위험 차단.
- 검증: 반전 sim(+TC→−v)이 램프에서 RED(unit_diag 미생성=진단펄스 미도달·dir=−1·basis 기록·CA[25] 문구·abort 순서 유지); 램프 후 반전(FlipAfterRampSim)은 diag K_a=−3.38e6 단언이 포착; design ValueError; 정방향 유닛 dir=+1 기록·완주 무영향.

**범용화(사용자 요구)**: 알고리즘=파라미터구동 범용(맨모터~감속기 실측 K_a로). EAS=이 드라이브 검증 advisory. 적응사이징·단위정확·검증(자기일관+F2)이 범용성 담보. 실기검증=이 감속기시스템(필드홀드아웃).
