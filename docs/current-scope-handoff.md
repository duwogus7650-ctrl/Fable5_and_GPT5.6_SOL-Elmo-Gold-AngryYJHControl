# Quick Tuning + 제한형 단일축 작업 인계서

상태: **MERGE BLOCKED · HARDWARE USE BLOCKED · PRIVATE DRAFT HANDOFF**<br>
기준 시각: 2026-07-17 KST<br>
활성 상태판: [`../tasks/status.md`](../tasks/status.md)<br>
후속 장비/센서 매트릭스: [`drive-feedback-validation-matrix.md`](drive-feedback-validation-matrix.md)

## 1. 저장소와 증거 기준점

- 작업 브랜치: `codex/quick-single-axis-handoff`
- 분기 기준 HEAD: `351a623`; 인계 리비전은 이 브랜치의 최신 commit을 사용한다.
- `origin`: 새 작업 저장소 `Fable5_and_GPT5.6_SOL-Elmo-Gold-AngryYJHControl`
- `source`: 원본 저장소 `Fable5-Elmo-Gold-AngryYJHControl`
- 인계 commit은 소스·테스트·문서 allowlist만 포함한다. `.omc/state` 생성 상태, vendor/firmware 범위,
  smoke media는 포함하지 않으며 로컬 working tree에는 제외된 media 변경이 남을 수 있다.
- 기존 사용자 변경과 이전 작업 산출물을 임의로 정리하거나 삭제하지 않았다.

2026-07-17 01:16 KST의 runtime 관찰 스냅숏에서는 제어 프로그램 PID 19968과 새 범위 모니터
PID 33500이 응답 중이었다. PID는 재실행 때 바뀌는 일회성 정보다. 제어 프로그램은 연결 상태 보존을
위해 재시작하지 않았으므로, 현재 프로세스가 아래 최신 working-tree 코드를 로드했다고 가정하면 안 된다.

## 2. 현재 활성 범위

이번 완료 목표는 다음 두 기능으로 한정한다.

1. 현재 Gold Twitter + EnDat 2.2 한 축의 Quick Tuning
   - P1 전류 식별/설계
   - 제한 전류 커뮤테이션 서명
   - P2 속도/위치 식별/설계
   - RAM trial, 검증, 복원, 별도 `SV`
2. `UM=5` finite PTP만 허용하는 제한형 Single Axis Motion

현재 범위에서 제외한 항목:

- EAS 전체 기능 패리티
- vendor 비공개 Quick/Expert 알고리즘의 동일 복제
- Expert Tuning 구현
- Recorder Viewer 확대
- Jog/Homing/Current/Sine 및 다축 구동
- CAN/EtherCAT/Programming/firmware update
- Gold 계열 전체 및 다른 feedback 조합의 자동 호환 선언

## 3. 이번 범위 변경 뒤 반영한 코드

### 3.1 Quick Tuning fail-closed 보강

- [`../autotune_current.py`](../autotune_current.py)
  - P1 preflight에서 `CA[18]`이 누락, 비유한 또는 0 이하이면 drive write 전에 RED로 중단한다.
  - 과거의 무한 PX guard 폴백을 제거했다.
- [`../autotune_velpos.py`](../autotune_velpos.py)
  - P2와 P2 verify는 live `CA[18]`을 요구한다.
  - P2는 live `KP[1]`, `KI[1]`을 요구하며 고정 기본값으로 계속하지 않는다.
- [`../main.py`](../main.py)
  - 일반 P2 실행은 현재 connection generation의 커뮤테이션 서명 GREEN을 요구한다.
  - 현재 세대 P1 결과의 유효한 phase-to-phase R/L을 P2 payload로 넘기며, 없으면 시작하지 않는다.
  - P1 새 실행은 이전 커뮤테이션 서명 권한을 폐기한다.
  - Phase 2 확인창은 고정 `21.2132 A`가 아니라 `선택 비율 × 실행 직전 live CL[1]` 계약을 표시한다.
- [`../operation_catalog.py`](../operation_catalog.py)
  - P2 on-motor verification을 `MOTION` operation으로 등록했다.

### 3.2 제한형 단일축 보강

- [`../single_axis_motion.py`](../single_axis_motion.py)
  - 상대 좌표뿐 아니라 session-absolute target도 현재 PX 대비 최대 delta를 검사한다.
  - absolute target을 사용한 `MAX_STEP_REV` 우회를 막았다.
- [`../main.py`](../main.py)
  - fresh telemetry와 이번 connection generation에서 검증된 Session Zero를 분리했다.
  - UI와 worker 양쪽에서 verified Session Zero가 없으면 move를 거부한다.
  - disconnect와 Encoder Maintenance는 Session Zero 권한을 취소한다.
  - disconnect 때 운영자, E-stop/STO, limit 확인 체크를 초기화한다.
- live finite PTP feature flag는 계속 `FINITE_PTP_LIVE_ENABLED=False`다.
- STOP closeout의 GREEN은 `MO=0/SO=0`과 전류 제거 확인이지 기계적 정지나 독립 STO 증명이 아니다.

### 3.3 범위 정리와 모니터

- 중단된 Recorder Viewer 확대 범위의 operation catalog/test 흔적을 제거했다. 기존 Recorder backend와
  이미 구현된 로컬 viewer를 삭제했다는 뜻은 아니다.
- [`../progress_monitor.py`](../progress_monitor.py)와 [`../tasks/status.md`](../tasks/status.md)를
  전체 EAS 패리티가 아닌 현재 두 기능 기준으로 교체했다.
- 표시값은 `범위 확정 100 / 오프라인 준비도 60 잠정 / 현 리비전 실기 0 NEED-DATA`다. 독립 검토에서
  P1 blocker 4건이 확인되어 기존 70에서 하향했다.
- `field_progress=0`일 때만 `LIVE NOT RUN`을 표시하며, 향후 양수가 되면 `EVIDENCE TO DATE`로 바뀐다.
- 실행 중 모니터만 재시작했고 제어 프로그램 프로세스는 재시작하지 않았다.

## 4. 현재 검증 증거

| 증거 | 결과 | 의미와 한계 |
|---|---:|---|
| Quick P1/commutation 집중 회귀 | 120 passed | mock/simulation/offline 경로 |
| Quick P2/transaction 집중 회귀 | 182 passed | mock/simulation/offline 경로 |
| single-axis/UI/safety/catalog/energy 집중 회귀 | 179 passed | mock/offscreen 경로 |
| monitor parser/watcher/render 계약 | 25 passed | 최신 100/60/0 schema, invalid/stale, 0→양수 field 전환 |
| `progress_monitor.py --smoke` | GREEN 100/60/0 | no hardware I/O |
| monitor 실제 Windows 렌더 | OBSERVED | 새 제목, 세 지표, status 본문 표시 확인 |
| 최신 전체 `pytest -q` | **1060 passed in 165.86s** | Python 3.14.5, `QT_QPA_PLATFORM=offscreen`, no hardware I/O |

앞의 481개 집중 테스트와 25개 monitor 테스트는 실행 집합이 겹칠 수 있으므로 506개로 단순 합산해
독립 테스트 수라고 주장하지 않는다. 사용자의 중단 요청 때 첫 전체 run과 남아 있던 pytest 자식
프로세스 두 개를 종료한 이력은 verdict가 아니다. 이후 private-repository handoff 검증에서 전체 suite를
처음부터 다시 실행했다. 첫 run은 새 P2 권한 계약을 반영하지 않은 persistence UI test setup 한 건을
검출했고(1059 passed, 1 failed), 제품 gate를 약화하지 않고 test가 current-generation P1 R/L과
commutation GREEN을 명시적으로 만들도록 수정했다. 집중 재현 1 passed 뒤 최신 전체 run이
**1060 passed in 165.86s**로 종료됐다. 이 최종 재실행은 진행률 100/60/0 갱신 뒤 수행했다.

과거 Gold Twitter 실기 이력은 알고리즘 개발의 참고 자료다. 그러나 현재 dirty working tree의 exact
revision, target identity, connection epoch와 결속되지 않았으므로 최신 코드의 live GREEN으로 재사용하지
않는다. 이번 범위 보강과 문서화에서는 drive I/O, 통전, 모션, 영점 변경, `SV`, firmware 작업을 실행하지
않았다.

## 5. 독립 확인 merge blocker와 잠금

독립 post-hardening 리뷰 뒤 주 에이전트가 관련 코드 경로를 재확인했다. 다음 네 항목은 모두
`OBSERVED / P1`이며, 이 Draft PR을 병합하거나 hardware에 사용하는 것을 차단한다.

| blocker | 관찰된 영향 | 필요한 수정과 음성 대조군 |
|---|---|---|
| P2 Verify가 commutation signature gate를 우회 | standalone verify가 현재 세대 서명 없이 300/900 rpm ladder에 진입 가능 | UI/worker 이중 gate; 서명 false에서 drive I/O 0 증명 |
| P1 `PreflightError` 뒤 설정이 남을 수 있음 | socket admission 실패 전 임시 gain/`UM=3`/`SC[8]` write, abort evidence 없음 | 모든 admission을 첫 write 전 수행; dirty 실패 시 full restore/readback, 실패하면 `UNKNOWN` |
| P2 drive-side critical limit가 fail-open | `SD`/`HL[2]`/`LL[2]`/`ER[2]` 거부·불일치 뒤에도 `MO=1` 가능 | enable 전 full-set exact readback; 각 register 거부·silent mismatch·timeout·restore 실패 대조군 |
| P1 검증 전 `SV` 가능 | on-motor verify는 RED stub인데 RAM trial 직후 Save가 활성화 | session-bound GREEN verification capability 전 Save/`SV` 금지; stale/foreign/failed/mutated token 대조군 |

최신 전체 1060-test GREEN은 실행된 mock/offscreen 경로에 대해서만 유효하다. 위 누락 음성 경로가
차단됐다는 뜻이 아니므로 merge gate로 승격하지 않는다.

### 5.1 그 밖의 남은 항목

우선순위가 높은 소프트웨어 항목:

1. 현재 코드가 `target_type = Gold Drive`로 일반화된 부분을 exact model/part-number capability registry로 교체
2. 통제된 제어 프로그램 재시작 뒤 실제 로드 revision과 UI 계약 확인

실기 전에 필요한 `NEED-DATA`:

- 물리 이동 범위, 출력축 환산과 안전한 +/− 방향
- FLS/RLS/STOP 배선, 극성, drive mapping과 양방향 작동 근거
- 최악 통신/샘플 지연을 포함한 정지거리와 여유거리
- 독립 E-stop/STO 차단 반응, 부하 낙하/브레이크/구속 조건
- target identity와 connection generation에 결속된 Session Zero 및 커뮤테이션 서명
- abort, 통신 상실, reconnect, 전원 재인가와 durability 시나리오

## 6. 재개 순서

### 단계 A — 완전 오프라인

1. 현재 프로세스/working tree identity를 다시 기록한다.
2. 전체 `pytest -q`를 새로 실행하고 결과를 보존한다. 2026-07-17 handoff 기준은
   `1060 passed in 165.86s`이며 코드 변경 뒤에는 다시 실행한다.
3. 위 네 blocker를 각각 수정하고 명시된 음성 대조군을 추가한다.
4. 전체 회귀를 통과시킨 뒤 구현자와 분리된 독립 재검토를 수행한다.
5. P0/P1 finding이 닫힌 뒤에만 오프라인 준비도 60을 재산정한다.

### 단계 B — runtime 통합, 아직 무모션

1. 드라이브가 disable·정지·무전류이고 사용자가 재시작을 승인했을 때만 제어 프로그램을 통제 재시작한다.
2. 새 코드/target identity/firmware/PAL/connection generation을 query-only로 확인한다.
3. UI 잠금, Session Zero 취소, disconnect 초기화와 P2 권한 표시를 확인한다.

### 단계 C — Quick Tuning 감독 실기

각 mutation 단계마다 fresh 현장 확인과 실행 승인이 필요하다.

1. query-only preflight와 원상태 snapshot
2. P1 제한 에너지 식별/설계
3. 별도 커뮤테이션 서명
4. P2 식별/설계
5. RAM trial → on-motor verify → restore 또는 별도 승인 `SV`
6. abort/통신 상실/재연결/냉간 audit

### 단계 D — 제한형 finite PTP 감독 실기

물리 gate가 모두 증명된 뒤에도 `FINITE_PTP_LIVE_ENABLED`는 코드 리뷰와 별도 승인 없이 열지 않는다.
Session Zero 뒤 최저 속도·가속도·전류·짧은 상대 이동부터 시작하고, 양방향·limit·STOP·comms-loss와
정지거리 evidence를 남긴다.

### 단계 E — 후속 하드웨어

현재 Twitter + EnDat 2.2 기준선을 먼저 고정한 뒤 증분형, Hall-only, Hall commutation + incremental
precision을 같은 Twitter에서 분리 검증한다. 그 다음 exact Gold Drum 모델과 part number를 확정하고 같은
모터를 새 capability profile로 반복 검증한다. 상세 admission 조건은
[`drive-feedback-validation-matrix.md`](drive-feedback-validation-matrix.md)에 있다.

## 7. 예상 소요시간

현재 상태에서 **실기 검증을 제외한 남은 소프트웨어 작업**은 `INFERRED` 약 **5–10 engineer-days,
달력 1–2주**다.

- P1/P2 admission·restore/`UNKNOWN`과 Save capability 정리: 3–6일
- 음성 대조군, 전체 회귀와 독립 재검토: 1–3일
- UI/문서/통합 마무리: 약 1일

큰 결함이 새로 나오지 않는다는 조건이다. 이 결과는 오프라인 code-complete 후보이며 motor safety나
성능 완료가 아니다. 현장 gate가 준비된 상태의 Quick + 제한형 single-axis 전체는 약 2–4주가 합당하다.
Expert Tuning은 이번 범위가 아니며, 현재 Gold Twitter용 좁은 Expert v1도 별도로 약 4–8주가 필요하다.

## 8. 완료 판정

오프라인 완료 후보는 다음을 모두 만족해야 한다.

- 최신 전체 suite 결과와 exact working-tree identity가 기록됨
- 필수 fail-closed 음성 대조군이 실제 mutation을 잡음
- restore 불확실 경로가 성공으로 승격되지 않고 `UNKNOWN`으로 잠김
- P1/P2/Single-Axis UI 문구가 구현된 권한과 검증 수준을 과장하지 않음
- 독립 리뷰의 P0/P1 actionable finding이 남지 않음

실기 완료는 별도 판정이다. 물리 gate, 최신 코드의 supervised transcript, closeout readback, recovery와
durability evidence가 없으면 `GREEN`, `safe`, `complete`, `Gold-compatible`을 선언하지 않는다.
