# AngryYJH Control — Elmo Gold Twitter 미니-EAS 제어 프로그램

Made by 여재현 (SPG). Elmo **Gold Twitter** 서보드라이브를 위한 자체 PyQt6 데스크톱 제어
프로그램. Elmo Application Studio III(EAS III)의 핵심 기능을 정품 Drive .NET Library +
실기 오라클로 재현한다.

> **이 문서는 "나중에 이어서 하기" 위한 진행상황 스냅샷이다.** 상세 연속성 로그는
> [`.omc/paf5-brief.md`](.omc/paf5-brief.md), 전체 대화이력은
> [`docs/session-history/claude-session-transcript.jsonl`](docs/session-history/)에 있다.

---

## 무엇인가

- **대상**: Gold Twitter / HW `GCON Revision E` / FW `Twitter 01.01.16.00` / S/N 22033647 / `Direct Access USB, COM3`.
- **통신 = Path A**: pythonnet(netfx)로 정품 `ElmoMotionControlComponents.Drive.EASComponents.dll`을
  파이썬에서 로드 → 2글자 Elmo 명령 + .NET Drive Recording/Personality API. **하드웨어가 아니라
  소프트웨어 골조·테마·교훈만** 선례([Fable5-SDD-Control-Program])에서 재사용.
- **실기 오라클 규율**: 모든 값을 실드라이브 대조로 확정. 모션/통전은 사용자 감독 하에서만.

## 실행 / 테스트

```bash
python main.py                    # GUI (테마: AYJH_THEME=qdd|angrybirds|amber)
python main.py --smoke            # 헤드리스 스모크 (연결/텔레메트리)
python main.py --smoke-feedback   # 23센서 피드백 패널
python main.py --smoke-autotune   # 오토튠 GUI 배선
python main.py --smoke-encoder    # Encoder Maintenance
python -m pytest tests/ -q        # 오토튠 유닛/시뮬 테스트 (49 passed)
```

## 화면 구성

| 화면 | 내용 | 상태 |
|---|---|---|
| **Motion** | 실시간 텔레메트리(PX/VX/PE/IQ/MO) + Soft Zero(PX=0, 세션·증분용) | ✅ 실기검증 |
| **Motor Settings** | Peak/Cont 전류(√2 rms), MaxSpeed, 극쌍, Motor Type 읽기·쓰기(MO=0+SV) | ✅ 실기검증 |
| **Feedback** | 23종 센서 동적 패널(EnDat 2.2 등), **Encoder Maintenance**(영구 원점) | ✅ 실기검증 |
| **Tuning** | 자체 전류루프 오토튠(Run/Abort/6단계/Apply) | 🔵 실기 거의 완료 |

## 지금까지 (핵심 성과)

### 실기 검증 완료
- **연결·텔레메트리·Motor/Feedback 읽기쓰기**: 실드라이브 대조 GREEN.
- **Encoder Maintenance 영점**(실기 확정): `TW[18]=0`(단일회전) + `TW[19]=1`(다회전, 소켓인자!
  `TW[19]=0`은 드라이브가 Drive error 21로 거부) → PX=0, **전원 off/on 후에도 유지(datum 영구,
  SV 불필요)**. 대조로 Soft Zero(PX=0)는 전원 후 절대위치로 복귀(휘발성).

### 자체 전류루프 오토튠 (Phase 1) — 실기 R/L 측정 성공
EAS의 게인 알고리즘은 재현 불가지만, **드라이브 명령으로 R·L을 실측 + 표준 PI 설계**로 게인 산출.
매 실기 런이 실물 특유의 문제를 하나씩 벗겨내며 완성:

1. 여진 주파수 한계(TS=100µs→f_max 1250Hz) → 주파수 자동산출.
2. 레코더 신호목록 → **.NET personality 업로드 흐름**(UploadPersonality + 5이벤트 콜백 + Start +
   FINISHED 폴 → CreatePersonalityModel → 254 신호).
3. 레코딩 업로드 → **.NET Drive Recording API**(RecordingData.Data 키는 **위치 0..N-1**, SignalIndex 아님).
4. **전압 단위**(가장 어려웠던 부분): "A/B/C/D Voltage"는 볼트가 아니라 **레그 PWM 듀티 카운트**(mid=3750=0V).
   보정 = 중성점차감 `v_A−mean(A,B,C)` + Vbus/7500 스케일 + **복소-Z 스큐 회전보정**(기록전압이 전류보다
   1.5·TS 앞섬). 드라이브 게인계 = **ph-ph**(KP=ω_c·L_pp, EAS 대비 −0.018%). KI = 2·α·ω_c/2π(EAS 매칭).

**실기 측정 결과(8회차, 감독 하)**: R_pp≈0.14–0.15Ω(터미널, 모터 0.119 + 케이블·FET 기생),
**L_pp=41.34µH(4주파수 산포 1%)**, KI=812.87(EAS 812.94와 −0.0087%), PM≈59°. 게이트 G2/G3/G4 통과.

### 자체 속도/위치 오토튠 (Phase 2) + 검증런 — 실구동 성공 (2026-07-15)

**측정 → 게인 산출 → 적용 → 검증까지 EAS 없이 앱 안에서 완결.**

- **플랜트 실측**: K_a = **2.76e6 cnt/s²/A** — 독립 **5회 재현**(2.7733/2.7537/2.7607/2.7545/2.7642e6,
  편차 0.7% 이내). I_c ≈ 0.45–0.48 A, i_ba ≈ 0.9–1.1 A.
- **검증런(F2/G5) GREEN** — 우리 게인(KP[2]=0.000166 / KI[2]=10.7 Hz / KP[3]=85.2114):
  300rpm OS **0.8%**·정착 292ms·I_ss 0.475A / 900rpm OS **0.3%**·정착 888ms·I_ss 0.518A.
- **EAS 게인 대조**(0.000155/22.1/181): 300rpm 0.8%·296ms·0.482A / 900rpm 0.3%·886ms·0.519A —
  **구분 불가한 동등 성능**. 단 이 시험은 **프로파일러 지배 구간**(정착의 실체 = AC 램프
  328ms/983ms)이라 두 세트 모두 "램프 완벽 추종"만 증명한다. 설계 차이는 외란 억제·더 빠른
  지령에서 드러날 것 → 결론은 "우리가 낫다"가 아니라 **"상용 EAS와 같은 설계점에 도달"**.
- **안전 장치**: 서명 게이트(i_ba·방향), K_a 열화 조기검출(직전 GREEN의 0.5× 미만 → RED),
  Apply 되읽기 검증(불일치·0·음수면 SV 금지), UM3 드래그 판별(기계 vs 커뮤 구분).

## 남은 것 (다음에 이어서)

- **CA[25]=0 결정실험** (근본 수리 후보): **EAS GUI의 Motor Direction을 Non-Invert로**(터미널 아님 —
  터미널로 쓰면 위저드가 저장설정에서 1을 재주입) → 위저드 → SV → Phase 2 서명 GREEN →
  **전원 사이클** → 서명 재확인. GREEN 유지되면 δ 복권이 사라진다(결정론 복원). 실패하면
  "전원투입마다 서명 게이트"가 상시 규칙. → `.bkit/btw-suggestions.json` btw-024.
- **앱 자체 커뮤테이션 식별** (마지막 EAS 의존, 필요성 확정): EAS 위저드가 이 감속기에서
  **"Positive and Negative Movements are Uneven"으로 실패**한다 — ±대칭 이동 전제가 백래시·정지마찰로
  깨지기 때문. 우리 HOLD-CONFIRM(유격 통과 vs 진짜 회전 구분) 로직으로 **백래시 내성 커뮤 ID** 설계 가능.
  → btw-001/007/012.
- **Phase 1 apply 경로 점검**: `autotune_current.py`의 KP[1]/KI[1] 쓰기에 같은 포맷 지뢰
  (`%g`류 → 긴 소수 → 무성 0 저장)가 있는지. Phase 2는 `_fmt_gain`(소수 ≤6자리)로 수리됨.
- **스펙 문서**: `docs/autotune-velpos-spec.md` §6에 적응 캡처창·정착 의미(프로파일러 램프 포함)·
  커뮤 2층 모델 반영.
- **모션 화면**: 자유 조그·위치이동(현재는 검증런의 JV 스텝만 — 일반 모션명령은 안전상 차단됨).

### 운영 규칙 (이 유닛 필수 — 매 전원 투입마다)

**유효 전기각 δ는 전원 세션 스코프의 RAM 상태다.** 저장된 CA[7]이 비트단위 동일해도 전원 사이클
하나로 δ가 0°→103°로 튄다(실측). CA[7]은 위저드 실행 기록일 뿐 커뮤 결정자가 아니다.

1. 전원 투입 → **재커뮤 없이 Phase 2부터** (healthy 착지 확률 ~17%)
2. 서명 확인: **i_ba = 0.9 ± 0.4 A AND +TC→+dpx**. RED면 EAS 위저드 → 다시 1.
   - 위저드 전 **출력축을 손으로 흔들어 정지마찰을 깨고 완전 정지 대기**(EAS 자체 Resolution:
     "wait for the motor to stabilize") — 이 요령으로 성공률이 크게 오른다.
3. **서명 GREEN 전에는 폐루프(JV/조그/위치이동) 절대 금지** — cos δ<0이면 어떤 게인이든 양의 피드백.
4. **위저드 세션에서 터미널로 CA를 만지지 말 것** — 커뮤 리셋 → MF 폴트 → 에러 58(SO must be on).

## 파일 지도

- `main.py` — PyQt6 GUI(DriveWorker 스레드 + 4화면 + 스모크).
- `elmo_link.py` — pythonnet 전송층(2글자 명령 + .NET personality/recording 래퍼, 모션 게이트).
- `autotune_current.py` — 전류루프 오토튠(측정·복소Z·스케일·게이트·게인식).
- `feedback_spec.py` — 23센서 EAS 패널 스펙.
- `theme_qdd.py` / `theme.py` / `theme_angrybirds.py` — 스킨.
- `docs/recording-api.md` — .NET Drive Recording API 그라운딩(리플렉션 확정).
- `.omc/paf5-brief.md` — 상세 연속성 로그(모든 결정·수치·실기 발견).
- `vendor/elmo-downloads/` — 정품 .NET 라이브러리·펌웨어·문서(사용자 다운로드).

## 안전

모든 설정 쓰기는 MO=0 게이트 + 확인 다이얼로그 + SV. 오토튠 통전은 사용자 클릭 + 통전경고 확인에서만,
Abort 즉시 안전정지(§6 abort 체인 MO=0→…→복원), 이상 시 자동 원상복원. **무인 통전 금지.**

[Fable5-SDD-Control-Program]: https://github.com/duwogus7650-ctrl/Fable5-SDD-Control-Program
