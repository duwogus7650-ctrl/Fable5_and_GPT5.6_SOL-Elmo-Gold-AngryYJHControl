# Expert Filter / Scheduling Contract Inspector v0.1

## 목적

이 화면은 EAS Expert Tuning의 advanced filter와 gain scheduling을 실제로 계산하거나
드라이브에 적용하는 기능이 아니다. 공개 command reference에서 확인 가능한 **구조만**
탐색하고, 문서 충돌과 누락 근거를 숨기지 않는 순수 로컬 evidence inspector다.

고정 authority:

- `DOCUMENTED TOPOLOGY ONLY`
- `LOCAL INSPECTOR`
- `NO MODEL`
- `NO EMULATION`
- `NO WRITE`
- `NO DRIVE / WORKER / COMMAND I/O`

## 근거 identity

- source: Elmo `MAN-G-CR`, Version 1.406, February 2013, pp. 138–184
- repository file: [`command-reference.txt`](command-reference.txt)
- SHA-256:
  `55F620EA0E35812BC754FC9B4F7B6C9AF714C1041AECC0EB6DCCAEB63A44F156`

이 문서와 현재 Gold Twitter `B01G` firmware의 정확한 parity는 아직 검증되지 않았다.

## 구현된 로컬 탐색

### Filter type

| code | 문서 이름 | 문서에 나온 physical parameters |
|---:|---|---|
| 0 | canceled | 없음 |
| 1 | second-order low pass | frequency, damping |
| 2 | first-order lead/lag | frequency, phase |
| 3 | second-order lead/lag | frequency, phase |
| 4 | notch | frequency, quality factor, attenuation |
| 5 | anti-notch | frequency, quality factor, amplification |
| 6 | general bi-quad | numerator frequency/damping, denominator frequency/damping |

각 항목의 exact transfer equation, discretization, prewarp, range, quantization은
`NEED-DATA`다. inspector는 parameter 이름을 보여줄 뿐 Bode나 coefficient를 계산하지 않는다.

문서에는 advanced filter의 zero-frequency DC gain이 1이고, 일반 slot의 다섯 번째
parameter가 type을 선택하면서 filter를 enable하며, type 변경에는 motor-off가 필요하다고
적혀 있다. inspector는 이 precondition을 표시하지만 어떤 KV 변경도 실행하지 않는다.

### Controller filter location

- velocity controller output: `KV[1..5]`, `[6..10]`, `[11..15]`, `[16..20]`
- scheduled velocity filter 1: type `KV[25]`, table `KG[190..441]`, mode `GS[16]`
- scheduled velocity filter 2: type `KV[30]`, table `KG[442..693]`, mode `GS[17]`
- position controller output: `KV[31..35]`, `[36..40]`
- scheduled position filter: `KG[694..945]`, mode `GS[18]`; activation index는 문서 충돌로 미선택

### `GS[2]` mode

- `0`: disabled
- `1..63`: fixed controller-table index
- `64`: speed
- `65`: position
- `66`: profiler 상태에 따른 세 controller

화면은 입력값을 위 category로만 분류한다. controller 선택, 보간, 경계 전환,
speed/position source 처리 또는 gain 계산을 실행하지 않는다.

### `KG` table topology

- `KG[1..63]`: velocity `KI`
- `KG[64..126]`: velocity `KP`
- `KG[127..189]`: position `KP`
- 이후 12개 63-entry block: scheduled velocity 1/2와 scheduled position filter의 P1..P4

command reference 표의 velocity `KP` 단위 문자열은 `A/(counts/s)`다. peak/RMS와 phase/line
basis가 이 표에서 확정되지 않았으므로 P2 MODEL의 `A_peak/(cnt/s)`와 자동 등치하지 않는다.

## 보존한 문서 충돌

1. `KG[]` attribute header는 index range를 `1..504`로 적지만 같은 command 표는
   `KG[945]`까지 정의한다.
2. scheduled position filter activation은 KV 표/notes에서 `KV[45]`,
   GS/KG 절에서 `KV[50]`로 서로 다르다.
3. `KV[]` attribute header는 index range를 `1..90`으로 적지만 location 표에는
   velocity-presentation filter `KV[91..95]`가 있다.
4. GS 개요는 position scheduling 관련 parameter를 `GS[18,20]`으로 적지만 상세 표는
   position boundary를 `GS[19]`, `GS[20]`으로 정의한다.
5. speed scheduling 개요는 `GS[1,6,8,10]`을 나열하고 `GS[1]` 설명은 최대 속도를
   `GS[8]`로 적지만, 상세 표는 최대 속도를 `GS[6]`, speed source를 `GS[7]`로
   정의하고 `GS[8]`은 Reserved로 표시한다.

inspector는 어느 한쪽을 임의 선택하거나 정규화하지 않는다.

## 누락 근거

- repository evidence set에 SimplIQ Software Manual §15.4 gain-scheduling algorithm이 없음
- 현재 Gold Twitter B01G firmware와 MAN-G-CR 1.406의 exact parity 미확인
- exact transfer/discretization/prewarp/range/cascade/quantization/saturation/anti-windup
- speed/position table interpolation과 boundary behavior

따라서 `tuning.expert.filter.offline.evaluate`와
`tuning.expert.scheduling.offline.evaluate`는 계속 `NEED-DATA`다.
새 `*.evidence.inspect` 두 operation만 `LOCAL_UI · PARTIAL`이다.

## 구현 identity와 검증

- pure immutable source: [`../expert_filter_scheduling_evidence.py`](../expert_filter_scheduling_evidence.py)
- UI: Expert 세 번째 단계 `FILTER / SCHED EVIDENCE`
- operation catalog: [`../operation_catalog.py`](../operation_catalog.py)
- 테스트:
  [`../tests/test_expert_filter_scheduling_evidence.py`](../tests/test_expert_filter_scheduling_evidence.py),
  [`../tests/test_main_expert_tuning.py`](../tests/test_main_expert_tuning.py),
  [`../tests/test_operation_catalog.py`](../tests/test_operation_catalog.py)

검증:

- filter/scheduling evidence·P1/P2·UI·catalog 집중 회귀:
  `98 passed, 0 failed in 53.01s`
- 최신 working tree 전체 오프라인 suite:
  `1434 passed, 0 failed in 249.01s`
- Python 3.14, 1366×820 runtime smoke:
  `OFFLINE · READ ONLY`, `4 · Notch`, `Scheduled position filter`,
  `GS[2]=64 · SPEED`, 문서 충돌 5건과
  `NO MODEL · NO EMULATION · NO WRITE · NO DRIVE I/O`,
  Apply/Save `LOCKED`

이 runtime smoke는 필터 수치나 스케줄링 제어, 드라이브 응답을 검증한 것이 아니다.
