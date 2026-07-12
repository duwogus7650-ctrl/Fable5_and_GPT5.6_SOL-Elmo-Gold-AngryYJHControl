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

## 남은 것 (다음에 이어서)

- **G1 게이트 판정**: in-situ 스케일 교차확인이 주파수 의존 편향으로 ±10% 게이트에 부적합 →
  정보성 강등 or 대체 기준(fable-physics 판별 진행 중). 이후 전류루프 **첫 실기 GREEN**.
- **α/KI**: `KI = 2·α·ω_c/2π`로 EAS 매칭 확정(코드 반영됨).
- **미확정(실기)**: τ=1.5 vs 1.75·TS, 기생저항 배분, L 41 vs 명판 35.7 해석.
- **Phase 2**: 커뮤테이션 + 속도/위치 루프 튜닝(회전 수반).
- **모션 화면**: 조그·위치이동·구동(현재 모션명령은 안전상 차단됨).

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
