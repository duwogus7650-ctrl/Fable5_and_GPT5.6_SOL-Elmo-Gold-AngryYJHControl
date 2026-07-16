<!-- scope_progress: 100 -->
<!-- offline_progress: 60 -->
<!-- field_progress: 0 -->
<!-- progress_basis: scope=definition frozen; offline=INFERRED PROVISIONAL anchor within 55-65 after four independently confirmed P1 blockers; field=NEED-DATA because current-revision live proof has not run; these are not total-program or safety-completion scores -->

# Gold Twitter Quick Tuning + 제한형 단일축 모니터

상세 인계: [`../docs/current-scope-handoff.md`](../docs/current-scope-handoff.md)<br>
상태: **MERGE BLOCKED · HARDWARE USE BLOCKED · PRIVATE DRAFT HANDOFF**<br>
업데이트: 2026-07-17 KST

## 중단 및 재개 기록

- 사용자 요청 시 실행 중이던 전체 `pytest -q`와 독립 리뷰를 중단했고, 남아 있던 pytest 자식
  프로세스 2개도 식별해 종료했다. 그 중단 run에는 verdict가 없다.
- private-repository handoff 검증에서 전체 suite를 처음부터 재실행했다. 첫 run은 오래된 persistence UI
  test setup 한 건을 검출했고(1059 passed, 1 failed), P2의 P1 R/L + commutation GREEN 사전조건을
  명시하도록 test만 수정했다. 집중 재현은 1 passed였다.
- 최신 전체 결과: **1060 passed in 165.86s**, Python 3.14.5, offscreen, hardware I/O 없음.
- 독립 post-hardening 리뷰에서 아래 P1 blocker 4건을 확인했고 주 에이전트가 해당 코드 경로를 다시
  대조했다. 따라서 1060-test GREEN은 유지하되 merge·실기 사용 판정에는 쓰지 않는다.
- hardware tuning/motion은 계속 차단한다. private branch/Draft PR은 다른 오프라인 로컬에서 결함 수정과
  회귀를 이어가기 위한 인계본일 뿐이다.

## 이번 목표

- **포함:** 현재 Gold Twitter 한 축에서 Quick Tuning(P1 전류 → 커뮤테이션 서명 → P2 속도/위치)과
  `UM=5` 제한형 finite PTP 단일축 구동
- **제외:** EAS 전체 복제, vendor 비공개 알고리즘의 동일 구현, Recorder 확대, 다축·네트워크 기능,
  Expert Tuning 구현, Gold 계열 전체 호환 선언
- **현재 대상 계약:** Gold Twitter + EnDat 2.2 + Direct Access USB. 마지막 관찰 identity는 PAL 90,
  `Twitter 01.01.16.00`이지만 exact timestamp/connection epoch가 없어 `STALE/UNVERIFIED`이며 이번
  리비전의 실기 증거로 재사용하지 않는다.

## 현재 증거

- `OBSERVED / OFFLINE`: 변경 후 집중 회귀 **481 passed**
  - Quick P1/commutation: 120
  - Quick P2/transaction: 182
  - 단일축/UI/safety/catalog/energy: 179
- 이번 보강과 모니터 갱신에서 드라이버 I/O, 통전, 모션, 영점 변경, `SV`를 실행하지 않았다.
- `OBSERVED / OFFLINE`: 최신 전체 회귀 **1060 passed in 165.86s**. 이 결과는 exercised mock/offscreen
  경로만 증명하며 hardware safety나 성능을 증명하지 않는다.
- 실행 중 제어 프로그램은 연결 상태 보존을 위해 재시작하지 않았다. 새 안전 보강은 통제된 재시작 뒤
  로드되며, 그 전에는 이 모니터 상태를 제어 프로그램의 runtime 상태로 해석하면 안 된다.

## 독립 검토 결과 — merge blocker

1. **P2 Verify 커뮤테이션 권한 우회:** 일반 P2와 달리 standalone `verify_vp`의 UI/worker가 현재 연결
   세대의 commutation signature GREEN을 요구하지 않아 300/900 rpm 검증 ladder 진입이 가능하다.
2. **P1 preflight 실패 뒤 설정 잔류:** free feedback socket 검사가 임시 KP/KI, `UM=3`, `SC[8]` write
   뒤에 있고 `PreflightError` 경로가 abort/restore/readback을 실행하지 않는다.
3. **P2 critical limit fail-open:** `SD`, `HL[2]`, `LL[2]`, `ER[2]` write 거부·불일치가 warning으로만
   처리된 뒤 `MO=1`이 가능하며, restore의 완전한 readback/`UNKNOWN` 잠금도 증명되지 않았다.
4. **검증 전 P1 gain 영구 저장:** P1 RAM trial 직후 Save가 열리고 on-motor `verify_run()`은 RED stub인데도
   `SV` commit이 가능하다.

위 항목은 `OBSERVED / OFFLINE`이다. 기존 테스트 통과는 해당 음성 경로를 충분히 차단한다는 증거가
아니며, 각 수정에는 no-I/O/restore/불일치/stale-capability 음성 대조군이 필요하다.

## 완료한 오프라인 보강

### Quick Tuning

- P1은 `CA[18]`이 누락·비유한·0 이하이면 drive write 전에 fail-closed한다.
- P2는 live `CA[18]`, `KP[1]`, `KI[1]` 누락 시 고정 기본값으로 계속하지 않는다.
- P2 시작 조건에 **현재 연결 세대의 커뮤테이션 서명 GREEN**과 **현재 P1 결과의 유효한 R/L**을 묶었다.
- Phase 2 확인창은 고정 21.2132 A 대신 `선택 비율 × 실행 직전 live CL[1]` 계약으로 표시한다.
- P2 on-motor verification을 공통 operation catalog의 `MOTION`으로 분류했다.

### 제한형 단일축

- 상대/세션 절대 좌표 모두 현재 PX 대비 최대 이동량 검사를 적용해 absolute 우회를 막았다.
- fresh telemetry와 **이번 연결에서 검증된 Session Zero(PX≈0)**를 분리하고, worker에서도 재검증한다.
- disconnect/encoder maintenance 때 Session Zero 권한을 취소하고 운영자·E-stop·limit 확인 체크를 초기화한다.
- `FINITE_PTP_LIVE_ENABLED=False`: 실제 finite PTP는 계속 잠겨 있다.
- STOP closeout의 GREEN은 torque disable 확인이지 기계적 정지나 독립 STO 증명이 아니다.

## 남은 소프트웨어 게이트

1. standalone P2 Verify에 현재 세대 commutation signature GREEN을 UI/worker 양쪽에서 강제
2. P1의 모든 fallible admission check를 첫 write 앞으로 옮기고 dirty 실패 시 disable/restore/readback,
   불확실하면 durable `UNKNOWN` 잠금
3. P2 critical limit full-set apply/readback을 enable 전 필수화하고 restore 실패도 `UNKNOWN`으로 잠금
4. 유효한 session-bound on-motor verification capability 전에는 P1 Save/`SV`를 차단
5. 위 음성 대조군과 최신 전체 회귀를 통과한 뒤 별도 독립 재검토
6. 실행 중 제어창의 통제된 재시작과 새 코드 identity 확인
7. `Gold Drive` 하드코딩을 exact model/part-number capability registry로 교체하기 전까지 다른 Gold 모델은
   자동 호환으로 승인하지 않기

## 현장 검증 게이트 — `NEED-DATA`

- 물리 이동 범위, 출력축 환산, 안전한 +/− 방향
- FLS/RLS/STOP 실제 배선·극성·drive mapping과 양방향 작동 시험
- 최악 통신/샘플 지연을 포함한 정지거리 및 여유거리
- 독립 E-stop/STO 차단 반응, 부하 낙하/브레이크/구속 조건
- target identity와 connection generation에 묶인 Session Zero 및 커뮤테이션 서명
- 저에너지·짧은 이동부터 시작하는 감독형 PTP, abort/comms loss/reconnect/durability 시험

이 항목들이 증명되기 전에는 현 리비전 실기 진행률을 올리지 않으며 live motion 잠금을 해제하지 않는다.

## 현재 범위 예상

- **실기 검증을 제외한 현재 남은 소프트웨어:** **5–10 engineer-days / 약 1–2주**
  (`INFERRED`; 독립 확인 P1 4건, restore/UNKNOWN, 음성 대조군, 전체 회귀·재검토·통합 마무리)
- 기존 3단계 Quick 흐름 안전 보강 마무리: **3–6 engineer-days / 4–10 calendar days**
- 안내형 Quick Tuning v1: **4–7 engineer-days / 약 1–2주**
- 제한형 단일축 bench + 현장 검증: **8–14 engineer-days / 약 2–4주**
- 두 작업은 일부 병렬화되므로 현재 목표 전체는 현장 준비가 되어 있으면 대략 **2–4주**가 합당하다.
  limit/STO/기구 조건이 준비되지 않으면 일정 문제가 아니라 `NEED-DATA`로 멈춘다.
- Expert Tuning은 현재 backlog다. 현 Gold Twitter용 좁은 Expert v1은 **약 4–8주**,
  EAS 전체 Expert 기능적 범위는 **약 6–12개월** 추정이며 이번 완료율에 포함하지 않는다.

## 이후 검증 순서

1. Gold Twitter + EnDat 2.2 기준선
2. 동일 Gold Twitter + 증분형 엔코더
3. 동일 Gold Twitter + Hall-only, 그리고 Hall commutation + incremental precision 조합을 분리 검증
4. exact Gold Drum 모델·part number를 확정한 뒤 같은 모터들을 새 capability profile로 반복 검증

Gold라는 공통 firmware/software 계열만으로 전류·전압·I/O·feedback·통신·보호·튜닝 설정의 동일성을
가정하지 않는다. 위 미래 조합은 모두 `CONDITIONAL / NEED-DATA`다.

## 지표 해석

- **범위 100:** 무엇을 이번 목표로 할지 확정했다는 뜻이며 구현 완료율이 아니다.
- **오프라인 60:** 현재 코드, 481-test 집중 증거, 1060-test 전체 회귀와 독립 확인 P1 blocker 4건을 함께
  반영한 `INFERRED PROVISIONAL` 표시값이다. 합리적 범위는 55–65이며 blocker 수정·음성 대조군·독립
  재검토 뒤 다시 산정한다.
- **실기 0 / NEED-DATA:** 최신 코드로 hardware motion/tuning validation을 아직 실행하지 않았다는 뜻이다.
  실패율이나 안전도 0이라는 뜻이 아니다.
