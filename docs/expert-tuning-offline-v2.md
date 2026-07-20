# Expert Candidate Lab v2 — Current → Velocity / Position Offline Model

기준일: 2026-07-18

## 판정

`Expert Candidate Lab v2`는 두 단계의 **순수 오프라인 MODEL** 도구다.

1. 명시적 phase-to-phase `R`, `L`, `TS`로 Current P1 후보와 Bode 응답을 계산한다.
2. 그 P1 MODEL과 명시적 `K_a`, `B`로 Velocity / Position P2 후보를 계산한다.

계산 버튼은 serial port, `ElmoLink`, `DriveWorker`, command queue, motor enable,
모션, RAM/SV 쓰기 또는 installed-gain readback을 사용하지 않는다. 결과는 설치값,
EAS 내부 알고리즘 동등성, 실기 안정성 또는 안전 승인값이 아니다.

현재 판정:

- P1/P2 수치 계산: `MODEL`
- 동결 기준점·대수 관계·음성 대조: `PASS`
- EAS Expert 알고리즘/파일/화면 동등성: `NEED-DATA`
- filter 및 gain scheduling 모델: `NEED-DATA`
- 실제 드라이브 Apply/Save: `LOCKED`
- 실기 검증: 이 변경 범위에서 수행하지 않음

## P1 입력과 출력

P1은 v1 계약을 유지한다.

| 항목 | 단위·기준 |
|---|---|
| `R_pp` | Ω, phase-to-phase, finite `> 0` |
| `L_pp` | H, phase-to-phase, finite `> 0` |
| `TS` | s, finite `> 0` |
| 목표 대역폭 | Hz, 선택값, finite `> 0` |
| KI 규칙 | `eas_ratio` 또는 `pole_zero` |
| 출력 | `KP[1]` V/A, `KI[1]` Hz, crossover Hz, phase margin deg |

P1 계산이 완전히 성공한 뒤에만 기존 P1 MODEL을 교체한다. 실패한 입력은 마지막
완전한 P1/P2 결과를 부분적으로 덮어쓰지 않는다. 새 P1이 성공하면 그 P1에 종속된
오프라인 P2 projection은 폐기하고 다시 계산하도록 표시한다. 계산 뒤 입력을 편집하면
기존 immutable 결과는 historical evidence로 보존하되 visible gate를 즉시 `STALE`로
강등하고, 다시 계산하기 전에는 P2 입력 authority로 사용할 수 없다.

## P2 입력·단위 계약

P2는 마지막으로 성공한 `CurrentPlant`와 `CurrentCandidate`를 명시적으로 요구한다.
installed-drive readback을 암묵적으로 입력으로 사용하지 않는다.

| 항목 | 단위·기준 | 조건 |
|---|---|---|
| `K_a` | encoder `cnt/s²/A_peak` | finite, `> 0`, repository MODEL 범위 |
| `B` | `A_peak/(cnt/s)` | finite, `>= 0` |
| velocity basis | encoder counts/s | 고정 |
| current basis | peak amperes | 고정 |
| `TS` | P1 MODEL의 sampling time | even integer `40..120 µs` |

`I_c`는 비선형 Coulomb friction이므로 이 선형 소신호 P2 설계에서 계산하지 않는다.
UI는 `excluded from linear P2 MODEL`로 표시한다. RMS/peak, rpm/counts/s,
phase/line 또는 사용자 단위를 자동 변환하지 않는다.

현재 `40..120 µs`와 P1 `TS` 재사용은 Gold command reference 및 이 저장소의
현재 모델 계약을 결합한 제한이다. velocity/position 실행주기와 current `TS`의 관계를
모든 펌웨어/제품에 대한 Elmo 공개 법칙으로 주장하지 않는다.

## P2 수치 모델

구현은 [`../expert_tuning_offline.py`](../expert_tuning_offline.py)의 immutable
`VelocityPositionPlant`와 `VelocityPositionCandidate`다. 검증된 기존 순수 계산
`autotune_velpos.design_vp_gains()`를 감싸되 입력과 반환값을 다시 fail-closed 검증한다.
P1 crossover/PM은 exact `R/L/TS`에 대해 재계산해 candidate provenance를 결속한다.
P2도 delegate의 `ok`를 신뢰하지 않고 gain law, 최종 iteration trace와 full-loop margin을
다시 계산한 뒤 모든 결과가 일치할 때만 candidate를 반환한다.

사용 모델:

- `D = K_a · B`
- `P_m(s) = K_a / (s + D)`
- `C_v(s) = KP[2] · (s + 2π·KI[2]) / s`
- `L_v = C_v · H_ci · P_m · exp(-1.5·TS·s)`
- `L_p = KP[3] · (L_v / (1 + L_v)) / s`

출력:

- `KP[2]` — `A_peak/(cnt/s)`
- `KI[2]` — `Hz`
- `KP[3]` — command reference 표기 `rad/s`; count-domain 모델 차원은 `1/s`
- current/velocity/position crossover와 phase margin
- velocity gain margin
- `D`, model bandwidth, bounded reduction count, model gate

정확한 교정 표현:

> MODEL — single-point calibrated on the current Gold Twitter/motor/TS combination; not an Elmo-published law, not generalized across motors, feedbacks, firmware, or Gold products.

따라서 `MODEL GATE PASS`도 EAS parity, hardware stability, field `GREEN` 또는 다른
Gold Line 제품 호환성을 뜻하지 않는다.

## Filter와 gain scheduling 경계

- Filter: KV slot/type 이름과 unity-DC-gain 설명은 공개 자료에서 확인했지만 정확한
  transfer function, discretization/prewarp, 수치 범위, cascade, saturation 및 현재
  firmware readback 계약이 부족하다.
- Gain scheduling: `GS[2]` mode와 KG table 개념은 확인했지만 table selection,
  interpolation, boundary behavior, 단위 충돌을 확정하지 못했다.

그래서 v2 결과는 `GS[2]=0 ONLY`, `FILTER NEED-DATA`로 고정한다. `KV`, `GS`,
`KG` emulation 또는 write를 제공하지 않는다.

## 검증 근거와 한계

동결 MODEL 기준점:

- `R_pp=0.139 Ω`, `L_pp=41.6 µH`, `TS=100 µs`
- `KP[1]=0.07177 V/A`, `KI[1]=812.939 Hz`
- `K_a=5.794e6 cnt/s²/A_peak`, `B=1e-7 A_peak/(cnt/s)`
- 예상 `D=0.5794 1/s`, `KP[2]≈7.8961e-5`, `KI[2]≈10.69998 Hz`,
  `KP[3]≈85.2114`, velocity PM≈67.6°, GM≈15 dB, position PM≈81.1°

테스트는 위 기준점 외에 다음을 고정한다.

- `KP[2]·K_a`, `2π·6.805·KI[2]`, `5.369·KP[3]`의 독립 대수 관계
- immutable/deterministic 결과, `B=0` 경계
- bool/string/0/음수/NaN/Inf, 잘못된 단위 basis와 TS 거부
- delegate의 누락·음수·비finite·무제한 trace 반환을 거부하는 mutation 대조
- 다른 R/L/TS에서 만든 P1 candidate 및 모순된 delegate PASS/trace/margin 거부
- invalid UI 입력에서 이전 완전한 결과 보존
- 입력 편집 즉시 P1/P2 PASS를 `STALE`로 강등하고 stale P1의 P2 사용 차단
- worker/link/job 0개, installed readback·Verify·Apply·Save 권한 불변
- qdd/amber/angrybirds 세 스킨의 1366×820 무수평스크롤

이 검증은 Python/mock/offscreen 범위다. 실제 전류 인가, motor motion, firmware의
gain 의미, EAS 수치 일치 또는 closed-loop 안정성을 증명하지 않는다.
