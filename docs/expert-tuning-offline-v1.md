# Expert Candidate Lab v1 — Offline Model Contract

기준일: 2026-07-17

## 목적과 판정

`Expert Candidate Lab v1`은 명시적으로 입력한 모터 전류루프 모델로 PI 후보와
주파수응답을 계산하는 **오프라인 MODEL 도구**다.

- EAS Expert Tuning의 내부 알고리즘이나 화면·파일 호환을 재현했다고 주장하지 않는다.
- 계산 결과는 드라이브에 설치된 값, 실기 검증값 또는 안전 승인값이 아니다.
- 모터 Enable, 전류 주입, 구동, Recorder, 커뮤테이션, RAM 쓰기, `SV`를 수행하지 않는다.
- 후보값과 `INSTALLED / DRIVE READBACK` 값은 서로 다른 표시 권한으로 유지한다.

현재 판정:

- 오프라인 수치 계산: `MODEL`
- EAS Expert 동등성: `NEED-DATA`
- 현재 리비전 실기 검증: `NEED-DATA`
- 자동 Apply/Save: `LOCKED`

## 입력 계약

v1 전류루프 모델은 다음 SI 입력만 받는다.

| 입력 | 단위·기준 | 조건 |
|---|---|---|
| 저항 `R_pp` | Ω, phase-to-phase | finite, `> 0` |
| 인덕턴스 `L_pp` | H, phase-to-phase | finite, `> 0` |
| 샘플링 시간 `TS` | s | finite, `> 0` |
| 목표 대역폭 | Hz | 선택값; finite, `> 0` |
| KI 규칙 | `eas_ratio` 또는 `pole_zero` | 명시 선택 |

phase-to-neutral 값, RMS/peak 전류 또는 다른 dq 정규화 값을 자동 변환하지 않는다.
사용자가 기준을 명시적으로 맞춰야 하며, 다른 기준 문자열은 거부한다.

## 계산 경로

구현 파일은 [`expert_tuning_offline.py`](../expert_tuning_offline.py)다.

1. `CurrentPlant`가 단위·기준·finite/positive 조건을 검증한다.
2. `design_current_candidate()`가 기존 검증된 순수 함수
   `autotune_current.design_gains()`를 이용해 자동 후보를 만든다.
3. `evaluate_manual_current_candidate()`는 입력한 KP/KI의 모델 여유를 계산한다.
4. `current_frequency_response()`는 제한된 로그 주파수 격자에서 plant, open-loop,
   closed-loop 응답을 불변 튜플로 반환한다.

기본 설계법의 `eas_ratio` 상수는 현재 Gold Twitter/모터에서 확보한 EAS 단일점과
맞춘 값이다. 다른 모터·다른 TS·다른 Gold Line 제품으로 일반화됐다고 볼 수 없다.
따라서 결과 표시는 항상 `MODEL`이고, EAS 또는 실기 `GREEN`으로 승격하지 않는다.

## 안전 경계

오프라인 모듈은 다음 객체를 소유하거나 가져오지 않는다.

- `ElmoLink`
- `DriveWorker`
- Qt worker/thread
- serial port
- Elmo vendor DLL communication object

아래 작업은 Expert 화면에서도 별도 하드웨어 작업으로 남으며 현재 자동 실행하지 않는다.

- P1 식별, 커뮤테이션 서명, P2 식별·검증
- Gain Apply/Restore/Save
- Motor/Feedback/limit 설정
- `MO=1`, `TC`, `JV`, `BG`, Recorder arm
- `SV`, `LD`, `RS`, firmware 작업

## 검증

`tests/test_expert_tuning_offline.py`는 다음을 확인한다.

- phase-to-phase 동결 기준점의 KP/KI 재현
- 음수·0·NaN·Inf·잘못된 기준 거부
- 수동 후보의 finite margin
- 결정적이고 제한된 chart-ready 주파수응답
- 주파수·point budget 경계
- phase/line 기준 혼동 음성 대조

UI 검증은 후보값과 설치값을 분리하고, Expert 오프라인 조작이 worker 생성이나
드라이브 I/O를 만들지 않는지를 별도 테스트한다.
