<!-- scope_progress: 100 -->
<!-- offline_progress: 100 -->
<!-- field_progress: 85 -->
<!-- progress_basis: Planning indicators, not safety scores. Scope = the implemented feature inventory is enumerated. Offline = code/tests/documents reviewed (2237 passed). Field now includes the complete self-contained tuning chain (commutation repair, Phase 1, signature, Phase 2, Apply, on-motor verification) and jogging at rated speed, all without EAS. It still excludes STO/E-stop efficacy evidence, finite PTP, protection efficacy, durable SV writes, and Gold-family compatibility. -->

# 자립 튜닝 체인 + 정격 조그 실기 달성 · 원버튼 Quick Tuning

상태: **EAS 없이 전 과정 자립 · 정격 3600 rpm 도달 · 3550 rpm 연속 운전**

업데이트: **2026-07-22 KST**

> 이 문서는 **현재 상태**를 기술한다. 2026-07-19까지의 감사 경위(서명 RED,
> `MF=0x80`, 전 기능 잠금 상태)는 [`tasks/failure-ledger.md`](failure-ledger.md)와
> `docs/evidence/field-2026-07-19/`에 보존돼 있다.

---

## 1. 달성한 것 (실기 검증)

### 1.1 EAS 의존 종료

북극성이었던 **"eas에 의존안하고 우리가 만든게 곧 eas처럼"** 이 실기에서 성립했다.
2026-07-21~22 작업 전체에서 **EAS는 한 번도 열리지 않았다.** 커뮤테이션 진단·수리부터
게인 산출·적용·모터 검증·정격 운전까지 이 앱만으로 완결했다.

### 1.2 커뮤테이션 자립 진단·수리

전원 재인가로 `CA[7]`이 322로 돌아가면 인에이블 즉시 `MF=0x80`이 재현된다.
앱이 이를 감지해 **180° 플립을 자동 적용**하고 재검증한다.

| 증거 | 값 |
|---|---|
| `CA[7]` | 322 → −446 (자동, MO=0 게이트 + 정수 되읽기 검증) |
| enable_watch #1 | polls 2, `MF=128`, t_fault 0.05 s → FAULT_0x80 |
| enable_watch #2 | polls 31, `MF=0` → STABLE |
| 실기 성공 | 2회 (2026-07-22) |

물리 근거: cos δ와 cos(δ−180°)는 동시에 음일 수 없으므로 180° 플립은 반드시 안정
반평면으로 보낸다. `CA[17]=5`(시리얼 절대)라 δ가 결정론적이라는 것이 전제다.

### 1.3 튜닝 재현성

**Phase 1 (전류 루프)** — 5회

| | 범위 | 비고 |
|---|---|---|
| R (상간) | 0.1316 ~ 0.1385 Ω | 반복 통전으로 단조 증가(+5.2 %, 권선 승온 약 +13 °C 상당) |
| L (상간) | 43.40 ~ 44.00 µH | ±0.7 % |
| KI[1] | **812.87 Hz — 매회 동일** | 드라이브 TS 양자화 |
| 위상여유 | 51.1 ~ 53.8° | |

**Phase 2 (속도·위치 루프)** — 4회

| | 값 | 편차 |
|---|---|---|
| `k_a` | 1.785 ~ 1.826 ×10⁶ cnt/s²/A | ±1.1 % |
| `kp_vel` | 2.505 ~ 2.562 ×10⁻⁴ | ±1.1 % |
| `ki_vel` | **10.70 Hz — 매회 동일** | |
| `kp_pos` | **85.21 — 매회 동일** | |
| 속도 PM / 위치 PM | 68.9 ~ 69.3° / 81.7° | |
| 이득여유 | 14.8 ~ 15.1 dB | |

**모터 검증런 (우리 게인 설치 후)**

| 속도 | 오버슈트 | 정착 | 정상상태 전류 | 추종오차 |
|---|---|---|---|---|
| 300 rpm | 0.8 % | 292 ms | 0.716 A | 0.004 % |
| 900 rpm | 0.4 % | 883 ms | 0.751 A | 0.0013 % |

두 경우 모두 정착이 램프 완료보다 빠르다(292 < 328, 883 < 983 ms). 응답을 제한하는
것은 제어 루프가 아니라 가감속 프로파일이다.

### 1.4 정격 조그

| 지령 | 결과 |
|---|---|
| 500 / 1000 / 2000 / 3000 rpm | 정상 완주 |
| **3550 rpm** | **연속 운전 정상** (실측 3551.4 rpm, 0.290 A) |
| 3600 rpm (정격) | **3600.25 rpm 도달** 후 과속 가드 트립 (0.007 % 초과) |

3600 트립은 절대 천장이 정격과 정확히 같아 여유가 0이었기 때문이며 `161b5c6`에서
램프 한계와 동일한 1 rpm 여유를 부여해 수정했다. **다음 세션부터 3600 지령이 통과한다.**

정격은 전압 한계 속도라 그 지점 토크 여유가 0에 가깝다. 앱이 산출하는 상시 권장은
**3060 rpm**(0.85 × 정격), 전압 여유 경고는 **3240 rpm**(0.90 ×)이다.

### 1.5 모터별 자동 적응 (세션을 넘어 학습)

드라이브 신원 해시로 모터를 식별하고 프로파일을 디스크에 유지한다.

```
.omc/state/motor_profiles/elmo-sn4-sha256_3892d854….json
  effective_rated_rpm 3600        (VH[2]·60/CA[18], DRIVE_ONLY)
  pole_pairs 16                   (CA[19], DRIVE)
  cont/peak current 21.2132 / 70.7107 A
  ka_baseline     1.79e6 → 1.83e6 → 1.79e6
  signature_band  i_ba_ref 1.3298 → 1.4881 → 1.3931 A
  n_history       1 → 2 → 3
```

드라이브 파생 필드는 **매 연결의 실측이 진실**이고 학습 3필드만 이월된다(같은
드라이브에 다른 모터를 물렸을 때 이전 정격이 되살아나지 않게). 이월은 **드라이브
신원이 확인될 때만** 이루어진다 — 신원 불명 시 쓰는 공용 버킷이 한 모터의 베이스라인으로
다른 모터의 통전을 승인하면 안 되기 때문이다.

### 1.6 원버튼 Quick Tuning

커뮤ID → Phase 1 → 서명 → Phase 2 → Apply를 **승인 1회**로 실행한다. 순서와 정책은
순수 상태기계 `quick_tune_chain.py`(Qt·하드웨어·I/O 없음)가 소유하고 Qt 글루는
발사와 보고만 한다. 실기에서 전 과정 완주를 확인했다.

설계에 박힌 실기 교훈:

1. **서명은 반드시 Phase 1 뒤** — P1의 P1_CONFIG 트랜잭션이 서명을 무효화한다
2. **Phase 2 YELLOW면 Apply 자동 실행 금지** — 플래그 붙은 런의 게인은 자동 설치하지 않는다
3. **재커뮤 스킵은 분기가 아니라 단계 안에서** — 건강하면 커널이 스스로 path A
4. **Abort · DRIVE STOP · 연결종료가 모두 체인을 끊는다** — 안 끊으면 중단된 단계의
   결과가 다음 통전을 발사해 비상정지가 아무것도 못 멈춘다

---

## 2. 이번 세션 커밋 (10건, 전부 push 완료)

| 커밋 | 내용 |
|---|---|
| `6f3790d` | 서명 첫런에 잠정 모션 권한 부여 (부트스트랩 순환 해소) |
| `0ba0a7e` | 본펄스 벽시계 데드라인 + 런 진입 코스트다운 게이트 |
| `4329dfe` | 벽시계 수정 실기 확인 기록 |
| `75a7143` | 서명 통전 상한이 자기가 판정하는 밴드 상단에 도달하도록 (검열 해소) |
| `5626899` | 모터 프로파일 학습 상태 읽기 배선 (쓰기 전용 → 왕복) |
| `a336142` | 원버튼 Quick Tuning + 빌드 리비전 표시 + 가이드 램프 누적 |
| `ee160ed` | 검증된 P2 RAM 시험에 한해 조그 허용 |
| `43d2430` | Session Zero 일회용 버튼 수정 + 롤백 정지대기 트레이스 |
| `b6be57f` | hold-to-run 자기정지 수정 |
| `161b5c6` | 절대 과속 천장에 램프 한계와 동일한 여유 |

전체 회귀 **2237 passed**, 실패 0.

---

## 3. 다음 세션 절차 (오늘 실기로 확정)

```
연결
 → Phase 1 (Current)
 → Commutation Signature          ← 반드시 Phase 1 뒤
 → Phase 2 (Vel/Pos)
 → Set Session Zero               ← 반드시 Apply 앞
 → Apply P2 → Drive RAM
 → Verify Installed P2 on Motor   ← GREEN이어야 조그 권한 부여
 → Jog
```

### 3.1 순서가 강제되는 이유

| 게이트 | 요구 | 어기면 |
|---|---|---|
| 서명 | Phase 1이 지우므로 그 뒤에 | Phase 2가 잠김 |
| Session Zero | 미저장 P2 시험이 **없어야** | Apply 뒤엔 거부 |
| 조그 | Session Zero + **검증된** P2 시험 | 시험이 있어야 함 |
| Verify | 그 시험 **객체 본인** | 재Apply하면 재검증 필요 |

네 조건을 동시에 만족하는 순서는 위 하나뿐이다.

### 3.2 커뮤테이션 ID 실행 여부

- **앱만 재시작** → `CA[7]`이 유지되므로 커뮤 ID **불필요**, Phase 1부터
- **전원을 껐다면** → `CA[7]`이 322로 복귀하므로 재커뮤 필요. 단 현재 커뮤 ID는
  정밀 δ 보정에서 RED로 끝난다(§4.1) — 플립은 정상 적용되고 런도 깨끗이 닫히지만
  체인은 거기서 멈춘다. 개별 버튼으로 실행하고 이후 단계를 수동 진행하거나,
  §4.1을 먼저 수정한다

### 3.3 조그 안전

- `Run Held` **해제** = 데드만(누르는 동안만) / 체크 = 래치(`Stop Jog`까지)
- 3600 rpm 램프는 약 12초 — 데드만이면 그동안 계속 눌러야 한다
- `DRIVE STOP`은 전 구간에서 살아 있다

---

## 4. 미해결 결함

### 4.1 커뮤 정밀 δ 보정이 자기 트랜잭션에 막힘 (btw-030) · HIGH

```
통신 실패 'CA[7]=450': command blocked: persistence state UNKNOWN on this link
```

2026-07-21에 고친 자기 데드락과 같은 기제이나 **다른 경로**다. 그때는 180° 플립만
트랜잭션 밖으로 뺐고(`_write_ca7_between_runs`), 정밀 보정
(`commutation_id.py:649 _ca7_write_verified`)은 런 안에서 `CA[7]`을 쓴다.
베이스라인이 없어 **한 번도 실행된 적 없던 경로**라 오늘 처음 드러났다.

영향: 커뮤 ID가 RED로 끝나 원버튼 체인이 ①에서 멈춘다. 커뮤 수리와 클로즈아웃은 정상.

후보: **(1)** persistence로 막힌 쓰기는 RED 대신 **YELLOW로 정직 강등**하고 enable-watch
판정만 주장 — 작고 안전하며 '기준 없음' 경로가 이미 쓰는 방식. **(2)** `CA[7]`을
authorized phase에 편입 — 원칙적이나 권한 모델을 건드림. **(3)** 보정 루프 다중 패스 — 무거움.
**(1) 먼저, (2)는 별도 과제**를 권장한다.

### 4.2 P2_LIMITS 롤백 정지 증명 도달 불가 가능성 · MEDIUM

정지 증명은 `VX`가 **정확히 0**일 것을 요구한다(`elmo_link.py:986`).

| 사례 | 결과 |
|---|---|
| VX 435 cnt/s (0.40 rpm) | 0.1 초 만에 통과 |
| VX −112 cnt/s (0.10 rpm) | 12.1 초 122회 거부 후 실패 → UNKNOWN 락 |

**더 빠르던 축이 즉시 멈추고 더 느리던 축이 12초간 못 멈췄다** — 코스트다운 시간
문제가 아니며 예산을 늘려도 해결되지 않는다. 다만 각 사례 표본 1개씩이라 방향성·재현율은
미확정이고, **안전 증명을 표본 2개로 완화하지 않았다.**

`43d2430`에서 거부된 레지스터 값을 증거에 남기는 트레이스를 추가했으므로 다음
발생부터 감쇠인지 바닥인지 자동 판별된다.

복구 경로: 전원 재인가 + `Persistence Audit` (2회 검증됨).

### 4.3 고속 조그 중 "멈칫" · 미규명

3550 rpm 운전 중 `MOTOR STATE UNKNOWN`, `PX —` 표시와 함께 속도가 살짝 떨어졌다
재가속하는 현상을 육안 관측. **어떤 산출물에도 기록되지 않았다** — 조그 결과에는
재스탬프 실제 간격, 읽기 타임아웃, 데드만 놓침 카운터가 없다. 런 자체는 모든 기록된
지표에서 정상(`GREEN/stopped`, 복원 완료, 과속·폴트 없음).

가설(**미검증**): 데드만 250 ms 대비 재스탬프 100 ms 주기가 고속에서 시리얼 폴링과
경합해 밀림. 확인하려면 조그 루프에 재스탬프 간격·읽기 실패를 증거로 남겨야 한다
(§4.2에서 효과가 입증된 방법).

### 4.4 Session Zero 순서를 앱이 안내하지 않음 (btw-031) · MEDIUM

Apply 뒤에 Session Zero를 하려 하면 거부되고 Restore로 되돌아가야 한다. 후보:
체인에 Session Zero를 Apply 앞 단계로 편입(축 위치는 운영자가 정하므로 승인 창 고지 필요) /
Apply 전 안내 / 거부 메시지에 순서 명시.

### 4.5 원버튼 체인에 Verify 미포함 (btw-026 후속) · LOW

Verify GREEN이 조그의 열쇠가 됐으므로 체인이 Apply로 끝나면 수동 단계가 남는다.
Verify를 ⑥번으로 넣으면 완결되나 실제 회전이 늘어나 승인 창 반영이 필요하다.

---

## 5. 이 세션이 증명하지 않은 것

- **STO/E-stop 효력** — 여전히 `미검증`. 독립 증거가 없어 Finite PTP는 NEED-DATA로 잠겨 있다
- **소프트웨어 STOP은 STO가 아니다** — `DRIVE STOP`은 ST→MO=0 요청이며 독립 안전회로가 아니다
- **기계 정지의 독립 증명** — 정지 결과 문구 그대로
  "MO=0/SO=0 verified; mechanical stop is not independently proven"
- **보호 기능 효력** — 과전류·과온·위치오차 트립의 실제 동작
- **영구 저장(SV) 경로** — `PRODUCTION_GAIN_TRIALS_ENABLED=False`로 잠겨 있고 durable
  pre-assignment WAL authority가 미구현이다. **게인은 전원 재인가 시 사라진다**
- **다른 Gold 제품·다른 모터** — 프로파일 구조는 모터별로 설계됐으나 실기는 이 유닛 1대뿐
- **원버튼 체인의 독립 리뷰** — 세션 제약으로 작성자 자체 점검만 수행했고 작성/검토
  분리를 지키지 못했다. 실기 첫 실행은 주의 관찰이 필요하다

---

## 6. 참고

- 실패·막다른길 상세: [`tasks/failure-ledger.md`](failure-ledger.md)
  — 이번 세션 12건 추가(07-21 4건 + 07-22 8건), 기존 항목에 확인·정정 줄 추가
- 개선 제안: `.bkit/btw-suggestions.json` (btw-026 ~ btw-031)
- 실기 산출물: `.omc/state/` — 결과 JSON에 `_build_rev` 스탬프(조그 결과는 미스탬프)
- 커뮤 근거: [`docs/commutation-id-grounding.md`](../docs/commutation-id-grounding.md)
- 커뮤 ID 스펙: [`docs/commutation-id-p4-spec.md`](../docs/commutation-id-p4-spec.md)
