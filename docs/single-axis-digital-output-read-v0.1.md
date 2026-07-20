# Single Axis Digital Outputs · Read-Only Snapshot v0.1

## Outcome

Motion의 Single Axis 화면에 Gold Twitter `Output 1..4`의 현재
드라이브 논리 활성 상태와 `OL`/`GO` 구성을 한 번에 읽는 별도 패널을
구현했다.

이 기능은 **조회 전용**이다. EAS의 Digital Output 체크박스처럼 출력을
토글하지 않으며, 물리 핀의 전압·전류, 외부 부하의 실제 상태, 브레이크
동작, STO 시험 결과를 주장하지 않는다.

## Exact read contract

명시적 `Refresh Digital Outputs · READ ONLY` 한 번에 다음 query만 허용한다.

1. `OL[1]` .. `OL[4]`
2. `GO[1]` .. `GO[4]`
3. 최종 `OP`

각 query timeout은 150 ms, 전체 snapshot freshness 한계는 2.0 s다.
시작/종료의 `transaction_session_identity()`가 동일하지 않거나 하나의
값이라도 누락·비정상·문서 범위 밖이면 전체 snapshot을 `UNKNOWN`으로
비운다.

다음 경로는 포함하지 않는다.

- `OP=...`, `OL[N]=...`, `GO[N]=...` 또는 어떤 assignment
- `OB[N]`, `OC[N]`, `XO[N]`
- EAS Digital Output 체크박스 조작
- 출력 토글, 라우팅/기능/극성 변경
- Enable, Disable, UM 변경, 모션, Recorder, Apply, Save, `SV`

## Decoded meaning

| 표시 | 근거 | 경계 |
|---|---|---|
| `ACTIVE/INACTIVE · DRIVE LOGICAL ACTIVATION` | 최종 `OP`의 bit 0..3 | 물리 핀 전압/전류 또는 부하 상태가 아님 |
| `OL FUNCTION` | `OL[N]` bit-field | 현재 설정의 문서상 기능명; 기능의 전기적 효과를 시험하지 않음 |
| `POLARITY` | `OL[N]` bit 0 | `ACTIVE_HIGH/ACTIVE_LOW`; 실제 핀 측정 아님 |
| `GO ROUTE` | `GO[N]` | `OL` 기능, Port A/B output compare 또는 STO status indication routing |
| `5 V / 3.3 V logic` | Gold Twitter Installation Guide §4.6, §10.4.2 | OUT1/2는 5 V logic, OUT3/4는 3.3 V logic; 회로/부하 검증 아님 |

`GO[N]=7`은 **STO status indication output routing**일 뿐이다.
STO 입력 배선, torque isolation, 독립 E-stop 또는 STO 시험 통과로 해석하지
않는다.

## Document conflict retained

설치된 `OL Output Logic` 문서는 Attributes의 range를 `0..9`로 적지만,
같은 페이지의 bit-field/possible-values 내용은 Target Reached의 active-low/
active-high 값 `10/11`을 정의한다. 구현은 이 충돌을 숨기지 않고
`OL_RANGE_CONFLICT`로 보존하며, 읽기 decoder에서만 명시된 합집합 `0..11`을
허용한다. 쓰기 권한은 만들지 않는다.

## Frozen sources

| Source | SHA-256 |
|---|---|
| Installed Gold `OP Output Port.htm` | `BFDE83C2EC00D1FCD3F2A8ADA8CCF7288836DE0E510431591E8A7078EF61FDF6` |
| Installed Gold `GO Digital Output Source.htm` | `4D4E7CBCE1EADBA8ED820224B441AFC370D5E264676A4AD22CC399361CE247BE` |
| Installed Gold `OL Output Logic.htm` | `F6A33CF4609B61AA31EB36F3B811387537A8208B495ACCA81CFB9A7B93331291` |
| Local `MAN-G-TWIIG_s.pdf` | `F8AE035E8A1E621BEA7679B4B042551AB7F23AC203E3D59AA681ABC53A2E64F7` |

PDF의 §10.4.2를 page 62~63으로 렌더링해 OUT1/2 5 V logic,
OUT3/4 3.3 V logic 표와 회로를 시각 대조했다.

## Field observation

2026-07-19 KST, 현재 Gold Twitter `COM3`, firmware
`Twitter 01.01.16.00 08Mar2020B01G`, 앱의
`ONLINE · READ ONLY` 세션에서 명시적 refresh 한 번을 관찰했다.

- Output 1..4: 모두 `INACTIVE · DRIVE LOGICAL ACTIVATION`
- `OL`: 모두 `General purpose / ACTIVE_HIGH`
- `GO`: 모두 `Function via OL[N]`
- acquisition: 18.1 ms
- 최종 query: `OP`

이는 **현재 target의 드라이브 응답 관찰**이다. 같은 시각 EAS parity,
멀티미터/오실로스코프 핀 측정, 외부 부하, 브레이크, 출력 토글, fault/STO
자극은 수행하지 않았다.

## Verification contract

테스트는 다음을 고정한다.

- 정확히 4개 출력과 Gold Twitter logic-voltage 분류
- `OL` function/polarity와 `GO` route의 fail-closed decode
- bool, NaN/Inf, 비정수, 누락, 범위 밖 및 미지원 route의 전체 snapshot 거부
- exact query order와 150 ms/query
- assignment와 `OB/OC/XO` 미사용
- connection session 변경과 query error의 전체 snapshot 거부
- source SHA-256 4/4
- query-only transport와 worker typed-job allowlist
- noncanonical/late/disconnected/energizing UI signal의 blank 처리
- 세 skin에서 table contrast ≥4.5:1, horizontal scroll 0

현재 Digital I/O/transport/worker/catalog/UI 직접 영향 범위는
**276 passed in 53.27s / exit 0**, 전체 repository는
**1673 passed in 493.02s / exit 0**이다.

## Remaining NEED-DATA

- EAS same-moment `OP/OL/GO` parity
- 실제 OUT1..4 핀 전압/전류와 polarity
- 외부 부하 및 브레이크 회로/안전 상태
- output compare/STO indication routing의 현장 동작
- 출력 변경 transaction, readback, rollback, timeout/disconnect safe state
- 다른 Gold 제품의 출력 수·전기 특성·Port C 차이

따라서 이 v0.1은 **CURRENT TARGET READBACK OBSERVED /
PHYSICAL OUTPUT BEHAVIOR UNVERIFIED / OUTPUT ACTUATION NO-GO**다.
