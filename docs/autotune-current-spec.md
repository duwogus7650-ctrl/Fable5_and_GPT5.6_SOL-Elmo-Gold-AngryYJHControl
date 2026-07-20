# SPEC: 전류루프 오토튠 Phase 1 (fable-algorithm 2026-07-12, 프로토타입 검증)

신규 파일: `autotune_current.py` + `tests/test_autotune_current.py`. 전송층 = `elmo_link.ElmoLink.command()`
(MO=1/TC/SE는 `allow_motion=True` — 운전자 게이트 통과 호출만). 명령 근거 `docs/command-reference.txt`.
프로토타입(증거): `AppData/Local/Temp/claude/C--Users-user/7b5159aa-.../scratchpad/autotune_proto.py`.

## 0. 요약
정지 상태 **UM=3(스테퍼 강제정류, 센서 무관 → 23센서 전종 호환)** 로 통전, 드라이브 **레코더**로 전류·전압지령 기록,
**R=2점 DC 차분법**, **L=정현여진 |Z| 크기법**. 게인은 캘리브레이션 상수 2개로 산출. 모션은 B4 사전정렬 스냅(≤1.5극피치=1.5·CA[18]/CA[19] counts, 래치 전 소진)뿐 — 측정창은 무모션(θ_abort 강제).

## 1. 입출력
**AutotuneParams**(dataclass, 기본값): i_frac_low=0.25, i_frac_high=0.50 (0<low<high≤0.6·CL[1]),
freqs_hz=(800,1600) (f≤0.125/TS_s, 정수사이클), sine_target_amp=3.0[A amp], wc_override_hz=None,
ki_rule="eas_ratio"|"pole_zero", nameplate_r_pp/nameplate_l_pp_h=None(부트스트랩).
**AutotuneResult**: status(GREEN/YELLOW/RED), kp_v_per_a, ki_hz, r_phase_ohm, r_pp_ohm(=2×phase),
l_phase_h, l_pp_h, wc_rad_s, pm_deg, ts_us, evidence(dict), warnings(list). **모든 실패는 예외로 안 죽고 RED+사유 반환**(단 §6 abort로 드라이브 안전화 후).
**단위**: 드라이브 전류=amplitude A(실기 PL[1]=70.71↔50Arms); R/L 내부계산=per-phase(상간의 ½: 진리 R_ph=0.0595Ω L_ph=17.85µH); KP=V/A, KI=Hz, PI영점=2π·KI; TS=µs 정수(40–120 짝수).

## 2. 명령 (그라운딩)
MO(통전게이트, MO=0=유일 하드abort, p199) · UM=3(스테퍼,MO=0에서만변경,p298) · TC(스테퍼전류지령[A amp],MO=1필요,±PL[1],p283) ·
SC[8](UM=3 자동전류, **0 확인 필수**,p266) · SE[1..7](정현: [1]=1전류,[2]진폭,[3]주파수,[6]DC,[7]램프; **StopMgr 미적용→SW캡**,p270) ·
TW[80](SE 시작1/정지0,휘발,p291) · WS[75](SE 상태기,2=구동중,p315) · CA[41..44](소켓센서ID; **8=Virtual2-Sine/SE**,MO=0,p46) ·
CA[70](전류지령 가산소켓,MO=0,p51) · CA[45/46/47](위치/속도/커뮤 소켓,읽기로 충돌회피) · CA[17/18/19](커뮤/counts-rev/극쌍,읽기만) ·
RC/RG/RL/RP[0..3]/RR(레코더; RP[0]=1→TS양자, RR=2 즉시, RR==0 완료,p252-263) · BH(업로드; **헤더 물리단위계수 곱必**,p30) ·
KP[1]/KI[1](게인쓰기,최종만,p178) · TS(샘플링읽기,p289) · MC/CL[1..4]/PL[1]/LC(한계·포화플래그 읽기) · PX/VX/IQ/DV[1]/DV[8]/MF/SR/EC(감시) · SV(영속화,적용단계+동의후만,p281).
**금지**: CS(커뮤각오염), RS(초기화), XA[](Do not modify), TW[31](Not for user), BG/PA/PR/JV(불필요모션).

## 3. R/L 측정
**3.1 UM=3 근거(전센서호환)**: UM=3은 피드백 센서 없이 개루프 전기각으로 전류 인가(p298). 어느 센서든 R/L 경로는 센서 미사용. 센서는 (a)모션감시 임계 환산(PX,CA[18],CA[19]) (b)백업에만 등장 → 전부 read_feedback 값으로 파라미터화, **센서ID·극쌍 하드코딩 금지**(舊 11.25°=180/16극쌍 하드코딩은 폐기 — 반극피치[counts]=CA[18]/(2·CA[19]), CA[19] 판독불가 시 16 가정+경고). 정렬 스냅 최대 반전기주기=반극피치 기계각; 정렬후 d축→토크0→무모션. **단 정지≠정렬**: stiction(감속기 마찰)이 반정렬 정지점을 만들 수 있어, 측정전 사전정렬로 소진 필수(§7 B4).
**3.2 R = 2점 DC 차분** `R_ph=(V̄₂−V̄₁)/(Ī₂−Ī₁)`, V̄Ī=각 DC(0.25·CL[1],0.50·CL[1]) 정상창(끝 0.25s) 평균. **나이브 V/I 금지**(데드타임전압 수백mV=신호와 동자릿, 나이브 +38%, 차분 0.0%); 두 레벨 같은 부호(+) 유지가 소거조건.
**3.3 L = 정현여진 |Z|**: SE로 DC바이어스(TC=I₁) 위 f Hz 정현전류, 기록 V(t)I(t)를 f에서 복조 `X_f=2·mean(x·exp(−j2πf·k·TS))`, `|Z|=|V_f|/|I_f|`, `L_ph(f)=sqrt(max(|Z|²−R²,0))/(2πf)`, L=median. **위상 쓰지말것**(지령V는 1~1.5TS 지연, |Z|는 순수지연 불변). DC바이어스≥1.25×정현진폭→상전류 부호불변→데드타임은 DC만 오염. **분모는 지령 아닌 기록 실전류 |I_f|**(플랜트임피던스=루프밖 물리량). 고주파일수록 ZOH편향(2500Hz −2.7%)→기본 800/1600.
**3.4 레코딩채널(런타임해석)**: 신호 3종=전류지령(DV[1]상당)·실전류(IQ)·모터전압지령. 목록=personality(.NET CreatePersonalityModel+GetRecordingObject; RV[N] p265). 전압지령=`/voltage/i` 매치 중 `/bus/i` 제외(D/Q 둘다 기록, 크기 sqrt(Vd²+Vq²)); **없으면 RED+목록덤프**(추측금지). RP[0]=1,RG=1,RL=4096(≥0.2s@20kHz),RP[3]=0,RR=2, RR==0폴링(타임아웃3s), **BH 물리계수 곱**. 자가검증: 기록IQ평균 vs 폴링IQ ≤5%.

## 4. 게인 산출
```
ω_c = 0.2010 / TS_s            # TS_s=TS×1e-6; wc_override 있으면 2π·override
KP[1] = ω_c · L_ph
KI[1] = α · ω_c / (2π),  α=1.2705       # ki_rule="eas_ratio"(기본)
KI[1] = R_ph / (2π·L_ph)                # ki_rule="pole_zero"(보수)
```
**정직표기(리포트에 그대로)**: 0.2010·1.2705는 이 드라이브 EAS 실측게인 단일점 캘리브레이션(KP_EAS/L_np=4020.7→ω_c·TS=0.2010; 2π·KI_EAS/ω_c=1.2705). EAS는 명판 극영점상쇄(530.5Hz) 안 씀. 타 모터·TS 일반화 미검증.
**안정성 게이트(필수)**: `G(s)=KP(s+2πKI)/s·1/(L_ph·s+R_ph)·e^(−1.5·TS·s)` PM계산 → **PM≥45° AND ω_c·TS≤0.25 AND 0<KP≤100 AND 0<KI≤5000** 전부 통과=GREEN. PM<45면 ω_c×0.8 재계산(최대3회) 실패시 RED. (EAS게인은 이 모델서 0dB 767Hz·PM57.3°=게이트 근거.)

## 5-6. 아키텍처·Abort
**전역불변식**: I1 쓰기전 스냅숏 JSON 디스크存(`.omc/state/autotune_snapshot_<ts>.json`, 재접속복구). I2 전류지령총합(TC+SE)≤0.85·CL[1]. I3 MO=1 구간 500ms 주기 MF·LC·PX 폴링→MF≠0∥LC==1∥|ΔPX|>θ_abort→abort. I4 SV는 Phase E "적용" 밖 절대금지. I5 command실패=1s타임아웃×2재시도후 abort.
**P1_CONFIG 원본 정밀도**: WAL에 넣을 원시 drive 응답은 float 변환 전에 `Decimal`로 판정한다. discrete register는 exact integer여야 하고, 연속 register는 float 변환이 수치를 바꾸지 않아야 한다. sub-ULP 소수는 첫 assignment와 WAL 전에 RED다.
**모션임계(센서·극쌍 파라미터화, 2026-07-13 개정)**: 반극피치=CA[18]/(2·CA[19]) counts; 정렬허용(B1~B3, 래치 전)=반극피치×1.2; **사전정렬 완화가드(B4 램프 구간 한정)=1.5극피치=1.5·CA[18]/CA[19]**(정당 정렬스냅 허용; MF≠0·LC==1 가드는 그대로); θ_abort=max(4, CA[18]·2°/360)(홀 96 저해상도 바닥4) — **측정창 게이트, 절대 완화 금지**(모션은 역기전력로 R 오염: 실기 스냅 ~0.97V vs DC신호 0.37V).
**Abort(순서고정)**: A1 MO=0(최우선,7.5ms) → A2 TW[80]=0 → A3 TC=0 → A4 스냅숏복원(SE[1..7],CA[4s],CA[70],UM,게인) → A5 RR=0 → A6 RED+사유(복원실패는 warnings+"전원재투입 복원" 안내).

## 7. 의사코드 (27스텝)
```
P0 assert is_connected; assert MO==0 (MO=1이면 RED "STOP 후"; 자동disable 금지)
P1 read TS,MC,PL[1],CL[1..4],UM,KP[1],KI[1],SE[1..7],CA[17],CA[18],CA[19],CA[41..44],CA[45..47],CA[70],SC[8],SR,MF,BV,XP[2]
P2 validate TS∈[40..120]; CL[1]>0; MF==0 else RED
P3 write snapshot JSON (I1)
P4 resolve recorder signals(§3.4); 전압지령 없으면 RED+목록덤프
P5 gains: KP[1]<=0이면 nameplate로 부트스트랩(KP=(0.05/TS_s)·L_np_ph, KI=R_np_ph/(2π·L_np_ph), 스냅숏에 원값); 명판없으면 RED
A1 (MO=0) UM=3; SC[8]!=0이면 SC[8]=0
A2 소켓 s = (4,3,2) 중 CA[40+s] 미사용·ID8 미선점 첫째; 없으면 RED. CA[40+s]=8; CA[70]=s
A3 SE[1]=1;SE[2]=0;SE[3]=freqs[0];SE[4]=0;SE[5]=0;SE[6]=0;SE[7]=50
B1 [운전자게이트: 축확인 체크] MO=1(allow_motion)
B2 poll SO==1 (timeout 2s)
B3 안정성프로브 TC=0.10·CL[1]; record 0.2s; |mean(IQ_tail)−ref|≤10% AND std(detrend)≤5% else (부트스트랩 재시도 or abort)
B4 사전정렬(2026-07-13 개정 — 실기 RED |dPX|=2191>364 근본수리): PX가드를 1.5극피치로 완화 후
   래칫 사이클(최대 3회): PX시점폴→TC램프 **i2=i_frac_high·CL[1]까지**(10단계×100ms, 스텝별 (TC,PX) 트레이스 evidence)
   →settle 0.3s→i1로 복귀램프→settle 0.3s→종단PX; 사이클 종단 |ΔPX|≤θ_abort→수렴(게이트 즉시 조임: px_ref=종단PX, tol=θ_abort);
   3회 미수렴→RED "정렬 미수렴". 수렴 후 wait 1s; PX 2회폴 200ms→|ΔPX|≤θ_abort→px_ref 재래치.
   근거: 정지≠정렬 — i1만으로 래치하면 측정창에서 i2 인가 시 stiction 돌파 스냅이 모션게이트에 걸림(fix b);
   i2를 견딘 정지점은 측정 중 i2 재인가에 준정적으로 이탈 불가.
C1 record@I1(0.25s)→Ī₁V̄₁; I2로램프(0.3s); record→Ī₂V̄₂
C2 R_ph=(V̄₂−V̄₁)/(Ī₂−Ī₁); |Ī₂−Ī₁|<0.5A→RED; R_ph∉[1e-3,10]→RED
C3 TC→I1복귀(0.2s); CL[2]>=2이면 세그먼트≤0.8·CL[4]/1000 s
D1 for f: A_cmd=clip(sine_target_amp/|T_est(f)|,0,0.8·I1); SE[3]=f;SE[2]=A_cmd;TW[80]=1; poll WS[75]==2(1s); record≥0.18s; TW[80]=0;
    |I_f|<max(0.3A,5·noise)→증액재시도 else YELLOW; min(I_rec)<0.1·I1→A_cmd×0.6 재시도
D2 L_ph(f)=sqrt(max(|Z|²−R²,0))/(2πf); |Z|≤1.05·R→f×2 재시도1회
D3 L_ph=median; spread>0.15→YELLOW
E1 TC램프다운→0(0.3s); MO=0; 복원(게인은 원값유지)
E2 §4 게인계산+안정성게이트→status; evidence채워 반환
E3 [production "Apply P1 → RAM" · LOCKED] durable pre-assignment gain-trial WAL이 없으므로
   hardware-capable link는 persistence query·snapshot·assignment 전에 typed fail-closed한다.
   아래 apply/rollback 계약은 exact `SYNTHETIC_NO_HARDWARE` 링크의 회귀 전용이다: MO==0 확인→
   기존 KP[1]/KI[1] 전체 스냅숏→새 게인을 평문 소수 ≤6자리로 사전검증(과학표기 금지,
   반올림 손실 ≤0.5%)→각 쓰기 직후 되읽기(>0, 전송값 대비 ±0.1%). 중간 실패는 원래 두
   게인을 모두 복원·되읽기하며, 복원을 증명하지 못하면 시험 스냅숏을 유지한다.
E3b [synthetic/retained recovery "Restore P1 → Original"] 원래 두 게인을 전부 복원·되읽기하고
   SV를 보내지 않는다. 새 production trial은 만들 수 없으며 retained recovery도 Restore-only다.
   현재 E4는 정직한 RED stub이므로 session-bound on-motor verification capability를 발급할 수
   없다. 따라서 `Save P1 → SV`는 UI, worker, domain, transport 최종 경계에서 모두 잠긴다.
E4 [향후 사용자액션 "검증런" · 현재 NEED-DATA/LOCKED] 새 게인으로 B1~B3를 재수행하고,
   같은 drive identity·connection generation·trial fingerprint에 결속된 on-motor GREEN을
   증명하는 구현이 완료된 뒤에만 별도 Save capability 설계를 재개한다.
```

## 8. 엣지케이스(핵심)
MO==1시작→RED "STOP후"(자동disable금지). KP[1]==0+명판없음→RED. 전압신호없음→RED+덤프. 4소켓만석/ID8선점→RED.
SC[8]≠0→0클리어(복원원값). 사전정렬 스냅>1.5극피치(CA[19]기반)→abort; 래칫 3회 미수렴→RED "정렬 미수렴"; 래치 후 |ΔPX|>θ_abort→abort. CA[19] 판독불가→극쌍16 가정+경고(YELLOW). **CA[18]은 live finite positive read가 필수이며 판독불가/비유한/0 이하이면 어떤 write나 energization 전 RED로 fail-closed한다. 무한 PX guard 폴백은 금지한다.** 사이클 PX 판독불가(dpx=None)→수렴 아님(캡까지 진행→RED "무모션 증거 확보 실패"). 수렴 사이클 내 가역 변위 dev_max>θ_abort(감속기 컴플라이언스)→경고만(YELLOW, 하드페일 금지·사이클별 dev_max evidence 기록). MF=0x200000(스턱)→abort+세그먼트단축안내. LC==1(포화)→abort. abort A3(TC=0)의 err58 "Servo must be on"은 A1(MO=0) 성공 시 예상거동=steps 기록·경고 제외.
SE 미주입(2회재시도후)→RED "SE→CA[70] 미확인(U1)". Ī₂−Ī₁<0.5A→RED. R_ph<0∥>10→RED. |Z|≤1.05R→f×2. L(800)vs L(1600)>15%→YELLOW.
PM<45(3회감축후)→RED. 통신타임아웃→abort(재접속시 스냅숏우선). NaN응답→즉시abort(입구차단).

## 9. 테스트 오라클
**T1 실기(이 모터)**: R_pp 0.119Ω(±20/35%) · L_pp 0.0357mH(±15/30% **핵심물리**) · KP[1] 0.07177(±15/30%) · KI[1] 812.94(±2%, TS=50 결정론). 정직: KP/KI 근접은 부분적 구성보장, 반증가능한 건 R·L·TS.
**T2 중간**: V̄₁∈[0.15,1.2]V; 기록IQ vs 폴링IQ ≤5%.
**T3 단위(하드웨어불요, 시뮬드라이브 = 헤드리스 검증 대상)**: 이산플랜트(a=exp(−R·TS/L),b=(1−a)/R)+Elmo PI(u=KP(e+2πKI·TS·Σe))+1샘플지연+데드타임0.24V+20mA노이즈를 목ElmoLink로 감싸 전파이프 실행. 합격: R오차≤1%, L≤3%, KP편차≤3%, KI≤0.5%, **나이브 V/I가 +30%이상 틀림을 확인하는 회귀** 포함.
**T4 게이트**: EAS게인→§4모델 PM=57.3°±1°, 0dB 767Hz.

## 10. 미확정(라이브 1회 검증후 갱신)
U1 UM=3서 SE(CA[70]가산) 실주입? (근거有 미확인; 실패시 D1경로; 검증=TW[80]=1후 기록전류 f성분). U2 CL[4] 단위(s vs ms, 기본3000, ms해석·라이브확인). U3 전압지령 신호명(런타임해석·첫라이브 로그). U4 MO=1(UM=3) 즉시 SO=1? (B2흡수). U5 CA[42..44] 실값 로그.
