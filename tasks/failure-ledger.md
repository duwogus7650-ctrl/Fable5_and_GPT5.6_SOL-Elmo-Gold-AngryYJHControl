# Failure Ledger — 실패·막다른길 원장 (append-only)
새 항목은 파일 끝에 추가. 항목 삭제 금지. 틀린 내용은 해당 항목에
`정정 YYYY-MM-DD:` 줄을 덧붙여 바로잡는다.

## 2026-07-12 — Elmo 2013 CR의 센서-ID enum이 2020 펌웨어엔 불완전 — 실드라이브가 오라클
- 시도: fable-reader가 CR(Ver1.406, 2013)에서 EnDat=ID 9로 매핑
- 실패 이유: 실드라이브(FW 2020) CA[41]=30 반환. CR enum이 신규 펌웨어의 센서타입(EnDat 2.2=30, 멀티턴 16bit)을 커버 못함. commut(5)/res(19)/counts(65536)는 CR과 일치했으나 센서 ID만 문서보다 확장됨
- 대안·다음엔: 센서 타입 목록은 CR enum이 아니라 드라이브 personality(.NET CreatePersonalityModel)에서 받아야 완전. 임시로 라이브값(30)을 지도에 반영, 미지 ID는 'ID N (미확정)' 폴백
- 재사용 자산: elmo_link.py ElmoLink.read_feedback/SENSOR_IDS — C:/Users/user/Fable5-Elmo-Control-Program/elmo_link.py

## 2026-07-14 — CA[25]/CA[54]를 "방향 레버"로 본 모델이 틀림 — 진짜는 커뮤 오프셋 δ
- 시도: +TC에 −피드백이 나오자 "배선/센서 방향 파라미터가 반전됐다"고 보고 CA[54]=Invert, 이어서 CA[25]=1을 지시. 패리티 모델(w·(−1)^CA54)까지 세움
- 실패 이유: 모델이 3상태(S1/S2/S3)엔 맞았으나 4번째에서 붕괴 — CA[54]=0인데 +TC→+dpx가 나옴. **방향 반전의 정체는 sign(cos δ)** 였다(δ=커뮤 오프셋 오차). CA 파라미터는 "값을 바꾸면 커뮤가 리셋된다"는 부수효과로 상관을 만들었을 뿐. **CA[25]=1은 순기능이 실증된 적이 없고 오히려 커뮤 오염(δ≈75~103°)과 상관**. 판별 지문: 3개 독립 전류경로(K_a·I_c·i_ba)가 전부 cos δ배로 붕괴하는데 **가속도-단위 마찰 K_a·I_c는 불변**(관성·마찰토크는 그대로, 토크/암페어만 붕괴)
- 대안·다음엔: 방향이 뒤집히면 파라미터를 뒤지지 말고 **재커뮤 → 서명 게이트(i_ba 0.9±0.4A AND +TC→+dpx) → 불합격이면 재커뮤 반복**. 커뮤 건강은 파라미터로 보장 못 하고 **매번 측정**해야 한다. δ 역산 = acos(K_a/K_a_healthy)
- 재사용 자산: autotune_velpos.py DIR_FIX_MSG(서명 게이트 절차로 교체됨) + ka_baseline 게이트 + UM3 드래그 판별(기계 vs 커뮤)

## 2026-07-15 — 드라이브가 긴 소수 문자열을 에러 없이 0으로 저장 (KP[2] 무성 소실)
- 시도: `apply_gains_vp`가 `"KP[2]=%.9g" % 0.000166142...` → **`KP[2]=0.000166142303`(소수 12자리)** 전송
- 실패 이유: 드라이브가 **에러 162(BAD_NUMBER)를 낼 수단이 있는데도 조용히 0을 저장**(펌웨어 파서 결함). 같은 명령의 `KI[2]=10.6999833`·`KP[3]=85.2113988`(소수 7자리)는 정상 저장 — **유일한 차이가 소수 자릿수**. 값 크기 문제 아님(드라이브가 EAS의 0.000157을 정상 보유). 실기 확정: 손으로 `KP[2]=0.000166`(6자리) 치니 `1.660000e-04`로 정상 저장·SV 생존
- 대안·다음엔: **게인 쓰기는 소수점 이하 ≤6자리 평문 십진 고정**(EAS-네이티브 관측 포맷이 전부 ≤6자리 = 실증된 안전 포장). **과학표기 금지**(구 `%.9g`는 극소 게인에 `KP[2]=1e-08`을 전송하던 추가 지뢰 — 입력 수용 미검증). 반올림 후 0 소멸·오차>0.5%면 **전송 전** 차단. 드라이브 출력은 과학표기로 오지만(1.660000e-04) 입력은 평문이어야 한다
- 재사용 자산: autotune_velpos.py `_fmt_gain` / `GAIN_DECIMALS_MAX=6` / `GAIN_ROUND_RTOL=5e-3`

## 2026-07-15 — Apply가 쓰기 검증 없이 SV까지 실행 → 잘못된 값이 영구 저장되고 "성공" 보고
- 시도: `apply_gains_vp`가 명령 전송 후 예외가 없으면 성공 반환 + `SV`. 되읽기는 화면 표시용으로만 존재
- 실패 이유: 위 KP[2]=0이 **조용히 SV로 영구 저장**됐고 함수는 "적용 성공"을 보고. 속도루프 비례게인 0(=직렬 PI에서 곱 전체 0 → 무토크 limp)인 채로 구동 직전까지 감. 코디네이터가 "Apply가 되읽어 대조한다"고 사용자에게 **잘못 설명**하고 그 전제로 Apply를 권한 것이 직접 원인
- 대안·다음엔: **드라이브 쓰기는 반드시 되읽어 대조**(전송값 기준 0.1% rtol + ≤0 절대 게이트), **전량 검증 통과 후에만 SV**, 부분 실패 시 SV 금지 + RAM 반영분 명시. 코드가 무엇을 하는지 **읽어보고** 사용자에게 말할 것 — 있다고 믿은 안전장치가 없었다
- 재사용 자산: autotune_velpos.py `apply_gains_vp`(3단 검증) / `APPLY_READBACK_RTOL=1e-3`

## 2026-07-15 — EAS 커뮤 위저드가 이 감속기 모터에서 작동 불가 + 전원 사이클마다 δ 재추첨
- 시도: 커뮤가 나쁘게 앉을 때마다 EAS 위저드로 재확립하고, 좋게 앉으면 SV로 보존하려 함
- 실패 이유: (a) **위저드 자체가 실패** — "Positive and Negtive Movements are Uneven". EAS는 로터를 ±로 밀어 **대칭 이동**으로 기준을 잡는데 백래시·정지마찰이 그 전제를 깬다(EAS 자체 Resolution: "wait for the motor to stabilize before choosing motor direction"). 성공해도 δ가 랜덤 착지(관측 표본 {≈0°,59°,75~82°,103°,115°,116°} → healthy ~17%). (b) **SV로 보존 불가** — 저장 CA[7]=174가 비트단위 동일한데 **전원 사이클 하나로 δ 0°→103°**(i_ba 0.887→4.05A, 방향 반전). **유효 커뮤 = 전원 세션 스코프의 RAM 상태**, CA[7]은 위저드 실행 기록일 뿐. (c) 위저드 세션에서 터미널로 CA를 만지면 커뮤 리셋 → **MF=128 폴트 → SO=0 → 에러 58(Servo must be on)**
- 대안·다음엔: **매 전원 투입마다 서명 게이트**(재커뮤 없이 Phase 2부터 — 17%는 그냥 통과). 위저드 전 **출력축을 손으로 흔들어 정지마찰 깨고 완전 정지 대기**(성공률 크게 상승, 실증). 위저드 세션에 터미널 CA 조작 금지. 근본 수리 후보 = EAS **GUI**의 Motor Direction을 Non-Invert로(터미널로 쓰면 위저드가 재주입) 후 전원 사이클 재현성 확인. 최종 해법 = **백래시 내성 커뮤 ID를 앱에 구현**(HOLD-CONFIRM 로직 재사용)
- 재사용 자산: autotune_velpos.py 서명 게이트(breakaway i_ba·direction) + `_um3_drag`(커뮤 무관 토크 오라클) + HOLD-CONFIRM(유격 통과 vs 진짜 회전)

## 2026-07-15 — 목(mock)이 실기 의미론과 달라 잠복 버그 2건을 은폐
- 시도: 시뮬(pytest) GREEN을 근거로 실기 실행
- 실패 이유: (a) 목이 **JV를 BG 없이 즉시 적용** → 실코드의 BG 누락(Elmo: JV는 다음 BG에서 발효)이 안 잡힘 → 실기에서 모터가 아예 안 돌아 v_ss 노이즈로 부호판정 랜덤 실패. PA는 이미 BG 필수로 고쳐놨는데 JV만 빠져 있었다. (b) 목이 **JV를 프로파일러 없이 순수 스텝**으로 모델링 → 캡처창(0.6s) < 램프시간(900rpm=0.983s @AC=1e6) 아티팩트를 못 잡음. 목에 프로파일러를 넣자마자 **D1의 동종 잠복버그**가 즉시 드러남(+900→−300 전이는 1.31s 필요한데 settle 0.8s 고정 → 감속 중 중간값을 정상상태로 기록 → **마찰 피팅 오염**). 실기에서는 시리얼 왕복이 sleep을 늘려 우연히 가려져 있었다(g 타이밍 버그와 동형)
- 대안·다음엔: **목을 실기 의미론에 정확히 맞춰라 — 맞추는 순간 잠복버그가 드러난다.** 특히 (1) 명령의 발효 시점(arm-then-BG) (2) 프로파일러/램프 (3) 타이밍이 통신 지연에 의존하는 곳. "시뮬 GREEN"은 목이 현실을 모델링한 만큼만 유효하다
- 재사용 자산: tests/test_autotune_velpos.py VPSim(`jv_target`/`jv` 분리 + AC 램프 + arm-then-BG) — 적응 캡처창 `record_s=max(0.6, t_ramp+0.4)`, D1 적응 settle `max(0.8, |Δjv|/AC+0.3)`

## 2026-07-21 — 커뮤 δ는 이 모터에서 "전원마다 재추첨"이 아니라 결정론적이었다 (모델 정정)
- 시도: 원장 2026-07-15의 "전원 사이클마다 δ 재추첨" 전제로, 전원 재인가하면 커뮤가 다르게 앉을 것이라 기대하고 반복 시도
- 실패 이유: **틀린 전제**. 이 유닛은 CA[17]=5(시리얼 절대)라 커뮤가 **CA[7] + 절대엔코더로 결정론적 계산**된다. 전원을 껐다 켜도 δ가 동일 → 인에이블마다 MF=0x80(Speed tracking, Admin p.85)이 100% 재현. "재추첨" 관측은 다른 모터/구성(21극쌍 기어드) 얘기였고 이 16극쌍 모터엔 적용되지 않는다
- 대안·다음엔: δ가 결정론적이면 **해법도 결정론적** — cos δ<0(=인에이블 즉시 MF=0x80)이면 **180° 플립 `CA[7] += 256`(wrap)** 이 반드시 안정 반평면으로 보낸다(cos δ와 cos(δ−180°)는 동시에 음일 수 없음). 실기 확정: CA[7] 322→−446 후 인에이블 버팀·i_ba=1.184A 검출·방향+1·expect-slip=slip(δ<45°). **EAS 무접촉으로 커뮤 진단+수리 성공**
- 재사용 자산: spikes/field_ca7_flip.py(게이트+되읽기 검증 플립), spikes/field_r0_snapshot.py(R0 복구지점), docs/commutation-id-p4-spec.md §1.1
- 참조: [[gpt56sol-elmo-jog-electrical-fault]]

## 2026-07-21 — 커뮤 런이 자기 안전-리밋 트랜잭션 때문에 자기 CA[7] 쓰기를 차단 (자기 데드락)
- 시도: 앱의 Commutation ID 버튼으로 180° 플립을 자동 적용
- 실패 이유: S0이 임시 안전리밋(SD/HL[2]/LL[2]/ER[2])을 **P2_LIMITS persistence 트랜잭션**으로 적용 → ACTIVE 기록 생성 → `persistence_unknown_latched()`가 `_persistence_record is not None`으로 **TRUE** → elmo_link 가드가 **모든 일반 할당을 차단** → S2의 `CA[7]=-446`이 "command blocked: persistence state UNKNOWN"으로 실패. CA[7]은 P1/P2/P1_CONFIG/P2_LIMITS/MOTOR 어느 authorized 집합에도 없어 우회로가 없다. 종료 시 리밋이 복원되며 기록이 RESOLVED로 바뀌어 **사후엔 원장이 깨끗해 보이는** 탓에 진단이 어려웠다(원장 mtime과 phase=P2_LIMITS로 규명)
- 대안·다음엔: (i) 플립을 리밋 트랜잭션 **이전**으로 옮기거나, (ii) 커뮤용 authorized 뮤테이션 경로(CA[7] 포함 phase) 신설. 실기 중엔 수동 플립(spikes/field_ca7_flip.py)으로 우회했고, 코드 수정은 오프라인 과제로 남김
- 재사용 자산: 진단법 = 원장 파일(`%LOCALAPPDATA%\AngryYJHControl\safety\persistence_unknown.json`)의 active/resolved + mtime 대조

## 2026-07-21 — S0의 "MF≠0이면 시작 거부" 가드가 자기가 고칠 폴트 때문에 시작을 막음
- 시도: 서명 실패로 MF=128이 래치된 상태에서 곧바로 Commutation ID 실행
- 실패 이유: S0이 MF≠0이면 무조건 거부 → 그런데 **MF=0x80은 이 알고리즘이 처리하도록 설계된 바로 그 폴트**다. 매번 전원 재인가로 MF를 지워야 했고, **전원 재인가는 RAM에 있던 CA[7] 수정을 322로 되돌려** 진전을 무효화하는 악순환까지 만들었다
- 대안·다음엔: MF가 **정확히 0x80**이면 오퍼레이터 확인 후 진행 허용(그 외 폴트는 기존대로 거부). 같은 부류의 갭을 베이스라인 전제조건에서도 이미 수정함(기준 없어도 플립까지 진행 → 정직한 YELLOW)
- 재사용 자산: commutation_id.py `st.no_ref` 경로 + tests/test_commutation_id.py 부트스트랩 테스트 2건

## 2026-07-21 — P1_CONFIG 롤백에 코스트다운 정착 대기가 없어 기어드에서 항상 UNKNOWN 락
- 시도: 커뮤 수리(플립) 후 Phase 1(전류 R/L 식별) 실행
- 실패 이유: Phase 1은 측정용 임시 P1_CONFIG(UM=3 스테퍼 + CA[44]=8·CA[70]=4·SE[2]/[3]/[7] 여진)를 걸었다가 되돌리는데, **롤백이 "비활성 + 정지" 증명을 요구**한다. 기어드 로터가 코스트다운 중이라 **VX=−32**(미세 회전)여서 정지 증명 실패 → 임시 설정(UM=3 등)이 드라이브에 남은 채 `configuration_state=UNKNOWN` 래치 → 앱 전체가 `PERSISTENCE UNKNOWN · P1_CONFIG · READ-ONLY LOCK`. 부분 복원만 됨(KP/KI·SC[8]·CA[42]/[43]·SE[1]/[4]/[5]/[6]은 복원, UM·CA[44]·CA[70]·SE[2]/[3]/[7]은 잔존)
- 대안·다음엔: **리밋 복원 경로에는 이미 있는 코스트다운 재시도가 P1_CONFIG 롤백엔 없다** — 동일하게 정착 대기(`_wait_rest` 류: VX+PX 이중증인 2연속 정지)+재시도를 넣어야 한다. 기어드/관성 부하에선 MO=0 직후 항상 잔류 회전이 있으므로 이 결함은 **재현율 100%**. 복구는 전원 재인가(플래시 원본 재로드) + Persistence Audit(기록 해소)로 확인됨("ORIGINAL PROFILE OBSERVED AFTER RESET")
- 재사용 자산: 리밋 복원의 코스트다운 재시도 로직(autotune_velpos.py 주석 :239-243), `_wait_rest` :721
- 참조: [[gpt56sol-elmo-jog-electrical-fault]]

## 2026-07-21 — 자기 데드락 수정: `_restore_limits`가 일회성 종결자라 "잠깐 풀기"가 불가 → 트랜잭션 2분할로 해결
- 시도: 커뮤 런이 자기 P2_LIMITS 트랜잭션 때문에 자기 CA[7] 쓰기를 막는 문제를, "쓰기 구간만 리밋을 복원했다 재적용"으로 풀려 함
- 실패 이유: `_restore_limits`는 **일회성 종결자**다 — `if ctx.limits_restore_finalized: return` 으로 시작하고 성공 시 그 플래그를 세운다(autotune_velpos:1206/1249/1321). 중간에 호출하면 리밋 복원이 종결 처리돼 이후 재적용·최종복원 계약이 깨진다. 즉 "임시 release" 의미론이 애초에 없다
- 대안·다음엔: **트랜잭션 2분할(C안)** 채택 — S2는 플립을 인라인으로 쓰지 않고 `pending_flip`으로 '요청'만 남기고 정상 종결(리밋 복원 완료), 래퍼 `run_commutation_id`가 **트랜잭션이 닫힌 사이**에 CA[7]을 쓰고(persistence 가드가 열려 있는 유일한 구간) `_run_once`를 한 번 재실행한다. 안전 종결자와 elmo_link 트랜스포트는 **무수정**. 2패스가 서로를 알아야 하므로 `prior_flips`(또 플립 요청 방지 + 이중폴트 판정 유지)와 `orig_ca7`(원복 목표가 플립된 값으로 오인되지 않게)을 인계하고, 증거·경고는 하나의 오퍼레이션으로 합성한다
- 재사용 자산: commutation_id.py `_write_ca7_between_runs` / `_run_once(prior_flips, orig_ca7)` / 증거 합성 로직
- 참조: 같은 날 원장 "커뮤 런이 자기 안전-리밋 트랜잭션 때문에…" 항목의 해결

## 2026-07-21 — 결함 ⑤ 부트스트랩 순환: 서명 GREEN이 Phase 2를 요구하는데 Phase 2가 서명 GREEN을 요구
- 시도: 커뮤 서명(Commutation Signature)으로 모션 권한을 얻어 Phase 2(Vel/Pos)를 실행
- 실패 이유: **순환 의존**이다. Phase 2 버튼은 `_motion_signature_is_current()`(= 서명 GREEN)를 요구하는데, 서명이 GREEN이 되려면 `ka_baseline`/`i_ba_ref` 베이스라인이 프로파일에 있어야 하고, 그 베이스라인은 **Phase 2 GREEN 런에서만** 기록된다. 첫 모터는 영원히 열리지 않는다. 여기에 `status = YELLOW if ctx.warnings else GREEN` 규칙이 겹쳐, P3에서 넣은 안전 클램프 경고(`SIGNATURE_ENERGIZE_ABS_MAX_A` 1.30 A 상한 적용 고지)가 **첫 런에서 항상 발화**하므로 첫 런은 구조적으로 절대 GREEN이 될 수 없었다
- 대안·다음엔: 판정을 `DriveWorker._signature_motion_authority(res_status, signature, final)`로 **추출**하고, 첫 런 증거가 물리적으로 충분하면 **잠정(provisional) 권한**을 부여한다 — 조건은 `band_source=="first_run"` and `first_run_verdict.status==YELLOW` and `detail.slip is True` and `direction==1` and `pass is True` and `MO==0` and `TC==0`. K_a 미측정은 Phase 2가 확정한다. 실기 증거(21:52:19 런: follow_ratio=0.0 완전슬립, i_ba=0.7179 A)로 `granted=True` 확인. **교훈: "GREEN이어야 다음 단계"류 게이트는 그 GREEN을 만드는 경로가 게이트 뒤에 있지 않은지 항상 역방향으로 검사할 것**
- 재사용 자산: `main.py::_signature_motion_authority`(순수 정적 메서드 — 실기 결과 JSON을 그대로 먹여 회귀 검증 가능), `tests/test_main_safety.py` 9케이스
- 참조: [[gpt56sol-elmo-jog-electrical-fault]]

## 2026-07-21 — Phase 2 버튼이 서명 후에도 안 열림: 게이트 조건이 둘인데 하나만 봤다
- 시도: 결함 ⑤ 수정 후 앱에서 `Run Phase 2 (Vel/Pos)` 활성화 확인
- 실패 이유: 버튼 조건은 `_motion_signature_is_current()` **and** `_p1_model_overrides_for_p2()` 둘 다인데 서명 쪽만 보고 원인을 찾았다. 실제 차단자는 후자 — Phase 1 결과 `_at_result`는 **인메모리**라 앱 재시작 시 None이 되고, 어제 GREEN(21:18)은 결함 ⑤ 수정 반영을 위해 앱을 재시작하기 전 인스턴스의 것이었다. 서명만 재시작 후(21:52) 실행돼 살아남아 비대칭이 생겼다
- 대안·다음엔: 진단은 **같은 조건을 공유하는 형제 위젯의 상태 차이**로 좁힌다 — `Verify Installed P2`(서명 조건만 요구)가 활성인데 Phase 2가 비활성이면 차단자는 서명이 아니라 나머지 조건 하나뿐이다. 설계 자체는 정상(오래된 R·L로 속도 게인을 설계하면 안 됨). 앱 재시작 후에는 **Phase 1 → 서명 → Phase 2** 순서로 한 세션 안에서 재실행할 것. `_advance_tuning_authority_generation()`은 연결 이벤트(`_on_connected`/`_on_failed`)에서만 증가하므로 Phase 1 실행이 서명을 무효화하지는 않는다(순서 자유)
- 재사용 자산: 없음
- 참조: 같은 날 원장 "결함 ⑤ 부트스트랩 순환" 항목
