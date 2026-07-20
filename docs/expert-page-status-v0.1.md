# Expert Local Page Status / Errors Inspector v0.1

## 목적

이 기능은 현재 프로세스 메모리에 이미 존재하는 Expert P1, P2, filter/scheduling
evidence의 상태를 한 화면에 모아 보여준다. EAS의 page tree를 복제하거나 드라이브 상태를
조회하는 기능이 아니다.

고정 authority:

- `LOCAL STATUS ONLY`
- `NOT EAS ENTER/APPLY STATE`
- `NOT INSTALLED`
- `NO CALCULATION`
- `NO WRITE`
- `NO DRIVE / WORKER / COMMAND / FILE / NETWORK I/O`

전체 판정은 항상 `PARTIAL`이다. Filter/Scheduling exact evaluator와 EAS Summary가
`NEED-DATA`인 동안 `READY`, `APPLIED`, `EAS COMPLETE` 또는 installed-drive 완료를
선언하지 않는다.

## 근거

| 항목 | 값 |
|---|---|
| 설치 문서 | `C:\Program Files\Elmo Motion Control\Elmo Application Studio III\NetHelp\Content\EAS_II_SimplIQ_Gold_UM\Drive Setup and Motion Activities.htm` |
| 참조 절 | `Drive Setup and Motion Activities §8.2.1` |
| SHA-256 | `BD824C372BBBE7F0928F0F805F51EDA2C5CD73150AB3C20F9DE6279E9006E8EE` |
| 문서에서 확인한 구조 | Expert page tree의 idle/changed/warning/error 상태와 Enter/Apply 계열 동작 설명 |

문서가 설명한 아이콘과 동작은 구현 범위를 정하는 근거일 뿐이다. 현재 화면은 EAS 아이콘
동등성, Enter, Apply, Apply All, Revert, 마지막 page 저장 또는 Summary recommendation을
구현했다고 주장하지 않는다.

## 상태 계약

| page | 상태 | 의미 |
|---|---|---|
| Current P1 | `MISSING` | complete local plant/candidate pair가 없음 |
| Current P1 | `INVALID` | 명시적 입력 오류 또는 plant/candidate 불일치 |
| Current P1 | `STALE` | 입력 편집 뒤 이전 immutable MODEL만 남음 |
| Current P1 | `CURRENT_LOCAL_MODEL` | 현재 입력과 일치하는 coherent local MODEL; `NOT INSTALLED` |
| Velocity / Position P2 | `BLOCKED` | current coherent P1 authority가 없음 |
| Velocity / Position P2 | `MISSING` | current P1은 유효하지만 complete P2 pair가 없음 |
| Velocity / Position P2 | `INVALID` | 입력 오류, 불완전 pair 또는 정확한 P1 object binding 불일치 |
| Velocity / Position P2 | `STALE` | `K_a/B` 편집 뒤 이전 immutable MODEL만 남음 |
| Velocity / Position P2 | `CURRENT_LOCAL_MODEL` | exact current P1 pair에 묶인 coherent local MODEL; `NOT INSTALLED` |
| Filter / Scheduling | `DOCUMENTED_PARTIAL` | immutable documented topology는 유효하나 evaluator/emulation/write는 `NEED-DATA` |
| Filter / Scheduling | `INVALID` | evidence authority나 불변 권한 계약이 기대값과 다름 |

P1 coherence는 plant/candidate type, basis, design gate와 독립 재계산한 crossover/phase
margin의 일치로 확인한다. P2 coherence는 현재 P1 객체와의 정확한 identity binding 및
동일 plant에서 재계산한 immutable candidate의 일치로 확인한다. 이전 PASS 문자열만으로
현재 상태를 자기서명하지 않는다.

## UI와 권한 경계

- 네 번째 Expert 단계 `4 · STATUS / ERRORS`에서 세 page 상태를 읽는다.
- 각 `Open` 버튼은 해당 로컬 Expert page로 이동할 뿐 계산이나 명령을 시작하지 않는다.
- Status page가 숨겨진 동안의 입력 변경은 dirty 상태만 남긴다. P1/P2 coherence 재계산은
  Status page를 실제로 열 때 한 번 수행해 text-edit마다 큰 모델을 반복 계산하지 않는다.
- 상태 화면을 열거나 갱신해도 candidate, installed readback, `_vp_result`, dispatch,
  Verify, Apply, Save 권한은 바뀌지 않는다.
- 잘못된 내부 타입이나 상태가 들어오면 전체와 모든 row를 `INVALID`로 표시하고 권한을
  부여하지 않는다.
- 이 기능은 Qt 외부의 순수 projection인 `expert_page_status.py`에 판정을 둔다.

## 검증 계약

- 빈 상태, 완전한 P1/P2, stale, invalid error, mismatched P2 binding을 각각 음성 대조한다.
- `open`, socket, subprocess와 GUI transport constructor를 poison하여 새 I/O가 없음을
  확인한다.
- installed fields, dispatch, Verify/Apply/Save와 기존 immutable object identity가
  보존되는지 확인한다.
- qdd/amber/angrybirds 세 스킨의 1366×820 layout에 네 번째 page를 포함한다.
- operation catalog는 `LOCAL_UI · PARTIAL`, gate 없음, menu 비활성으로 고정한다.

테스트 파일:

- `tests/test_expert_page_status.py`
- `tests/test_main_expert_tuning.py`
- `tests/test_operation_catalog.py`

실행창 smoke와 최종 회귀 수치는
[`current-scope-handoff.md`](current-scope-handoff.md)와
[`../tasks/status.md`](../tasks/status.md)에 기록한다.
