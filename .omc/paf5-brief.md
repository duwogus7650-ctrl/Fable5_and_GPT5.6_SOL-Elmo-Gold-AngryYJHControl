# PAF5 Brief — Fable5-Elmo-Control-Program

> **CURRENT POINTER — 2026-07-17:** 활성 범위는 Quick Tuning + 제한형 Single Axis Motion이다.
> 현재 working tree, 중단 지점, 검증 근거와 재개 순서는
> [`../docs/current-scope-handoff.md`](../docs/current-scope-handoff.md)를 우선한다. 이 파일의 아래 내용은
> 초기 프로젝트 경로와 장기 개발 이력을 포함한 historical context이며 현재 상태를 덮어쓰지 않는다.

메인 세션(Opus)이 유지하는 연속성 파일. 모든 fable-* 에이전트는 시작 시 이 파일을 읽는다.

## 목표
Elmo Gold Twitter 서보드라이브용 **미니-EAS 데스크톱 제어 프로그램**을 신규 제작.
범위 = 풀 데스크톱 GUI(USB 연결 · 실시간 텔레메트리 대시보드 · 모션/명령 · 설정 읽기·쓰기 ·
REC 로깅 · 열보호 · 펌웨어 탭). **실제 드라이브(COM3)까지 실동작**시키는 것이 목표.
선례이자 재사용 뼈대 = `C:\Users\user\Fable5-SDD-Control-Program`(OpenRobot VESC용 PyQt6 GUI).

## 프로젝트 경로 / 규율
- 작업 경로: `C:\Users\user\Fable5-Elmo-Control-Program` (**OneDrive 밖** — 바탕화면 리디렉션 동기화가 로컬을 비운 전례 회피).
- 벤더 파일: `vendor/elmo-downloads/` (사용자 다운로드 원본 안전 복사본).
- 규약 문서: `docs/man-g-cr_GoldLine_CommandReference.pdf`, `docs/man-g-adming_GoldLine_Admin.pdf`.

## 확정 사실 (grounding)
- **대상 드라이브**: Gold Twitter / HW `GCON Revision E` / 현재 FW `Twitter 01.01.16.00 (2020-03)` /
  PAL Ver 90.1 (V1) / S/N `22033647` / 연결 `Direct Access USB, COM3`.
- **펌웨어 파일은 독점 바이너리**(`.gabs`/`.abs`, 소스 없음). 제어 프로그램의 밑그림은 펌웨어가 아니라
  ① Gold Line Command Reference(2글자 명령 규약) + ② Drive .NET Library.
- **Drive .NET Library 1.0.0.8** (2015, C# SDK, `vendor/elmo-downloads/Drive .NET Library 1.0.0.8.zip`):
  - 메인 DLL `ElmoMotionControlComponents.Drive.EASComponents.dll` (참조 추가 대상).
  - 보조: `GMAS.MMCLibDotNET.dll`(CAN G-MAS), `canlibCLSNET32/64.dll`(Kvaser CAN) — 필요시 자동 로드.
  - **통신 방식: RS232 / USB(Elmo USB 드라이버) / UDP / Direct CANOpen / CAN Gateway.** USB 지원 확인됨.
  - API 패턴: `DriveCommunicationFactory.CreateCommunication(commInfo)` → `Connect()` / `Disconnect()`.
    명령은 2글자 텍스트(`AC`,`MO`,`UI[1]`,`CA[41]`)를 `SendCommand` / `SendCommandAnalyzeError`로 송신.
  - Personality(펌웨어에서 XML 업로드) = 파라미터 목록·에러코드·레코딩 신호 목록의 소스. `CreatePersonalityModel`.
  - 업/다운로드: personality, 파라미터(binary/text), user program, **firmware**, PAL, **Drive Recording**(setup/activate/upload).

## 재사용 (HARVEST, from SDD)
PyQt6 GUI 뼈대(`main.py`), 테마(`theme.py`), 펌웨어 인스펙터(`fw_inspect.py`), REC CSV 로깅 + 열보호 카드,
EXE 빌드 파이프라인(PyInstaller spec·GitHub Actions·Inno Setup). 통신층(vesc_*)은 **패턴만** — Elmo는 별개.

## 반복 금지 (WARN)
- VESC CAN 코덱 재사용 불가(프로토콜 상이). 펌웨어 .bin 리버스로 로직 복원 시도 금지(독점 바이너리).
- cp949 stdout 함정: 스크립트 시작 시 `sys.stdout.reconfigure(encoding='utf-8')`.
- 한글 경로 하드코딩 금지(NFC/NFD 무성 실패) — `os.walk`로 실제 파일명 읽기.
- 헤드리스 GUI 스모크에서 모달 `_toast`/`QDialog.exec` 스텁.
- PyInstaller `--windowed`: safe_print + exe rc==0 단언.

## 안전 경계 (실드라이브)
- COM 포트는 한 번에 한 앱만 점유 → **라이브 연결 테스트 전 EAS III를 Disconnect**해야 함.
- 스파이크·개발 중 **모션 인에이블(`MO=1`)·이동 명령 금지**. 읽기전용(버전/파라미터/상태)만.
  실제 구동은 사용자 감독 + 안전절차(고정·전류제한·STOP 선확인) 하에서만.

## 아키텍처 결정 — RESOLVED (Path A 확정, 증거 有)
- **Path A 확정**: pythonnet(netfx)로 공식 `EASComponents.dll`을 파이썬에서 로드 → PyQt6 SDD 뼈대 유지 +
  정품·안전 통신 + EAS 기능 패리티. **검증(2026-07-12, 하드웨어 없음)**: pythonnet 3.1.0 / Py3.14 64bit /
  CLR 4.0.30319에서 175 타입 로드. `DriveCommunicationFactory.CreateUSBCommunicationInfo("COM3")`,
  `IDriveCommunication.Connect/Disconnect/IsConnected/SendCommand`, `GetRecordingObject`,
  `UploadsAndDownloads`, `GoldStatusRegister`, `DriveLocator` 전부 노출 확인.
- **재사용 자산**: `elmo_link.py` (전송 시드, 모션명령 가드 내장) — reflection self-check GREEN.
  DLL은 `vendor/elmo-downloads/...zip`에서 `lib_net/`로 자동 추출.
- **남은 미해결**:
  - Elmo USB 드라이버 설치 여부(USB comm 의존) — 라이브 연결로 확인.
  - `Connect(out err)`/`SendCommand(out response)`의 pythonnet out-파라미터 실제 시그니처 — 라이브에서 확정.
  - 읽기전용 핸드셰이크 명령 정확한 니모닉(버전/상태/시리얼) — Command Reference로 그라운딩 후 사용.

## 안전 확인된 다음 마일스톤
라이브 읽기전용 핸드셰이크: EAS III Disconnect(COM3 해제) → `elmo_link`로 Connect → 버전/상태 읽기 →
EAS가 보여준 값(S/N 22033647, FW Twitter 01.01.16.00)과 대조 = 실기 오라클. **모션 인에이블 금지.**

## 신규 목표 (2026-07-12): 자체 자동튜닝 구축
EAS의 게인계산 알고리즘은 재현 불가(EAS 내부)지만, **드라이브 명령으로 R/L 실측 + 표준 PI 설계로 게인 산출**하는 우리만의 오토튠을 만든다. Phase1=전류루프(모션 최소)부터, 속도/위치는 다음.
**검증 오라클(핵심)**: 이 드라이브·이 모터에 EAS가 이미 튜닝한 전류루프 게인 = **KP[1]=0.07177 V/A, KI[1]=812.939 Hz**(실측). 우리 알고리즘을 같은 모터에 돌리면 이 값에 근접해야 함. 모터: R=0.119Ω·L=0.0357mH(ph-ph)·극쌍16·Peak50Arms. Elmo 게인정의(fable-physics): KP=V/A, KI=Hz, 영점=2π·KI, ω_c=KP/L. 튜닝 프리미티브: TW[4] current-loop ID, SE[] 정현여진, WS[91..] 응답계수(내부용). **모션/통전 안전 최우선(안전게이트·전류제한·abort·게인백업복원).**

### Phase1 전류루프 오토튠 — 시뮬(T3) GREEN (2026-07-12)
- 산출물: `autotune_current.py`(SPEC §7 27스텝: R=2점DC차분, L=정현여진|Z|median, ω_c=0.2010/TS·α=1.2705, PM≥45° 게이트, 스냅숏JSON, 고정순서 abort, 센서-불문 CA[18] 파라미터화) + `tests/test_autotune_current.py`(SimDrive 목: 이산플랜트+Elmo PI+1샘플지연+데드타임0.24V+노이즈20mA).
- **메인세션 독립검증**(에이전트 보고 불신뢰): pytest 30 passed / import OK / main.py --smoke exit0(무회귀) / T3 재현 R −0.011%·L −0.783%·KP −0.801%·KI −0.0087%·PM 57.55° — 전 항목 SPEC 허용 내. 나이브 V/I 회귀 +38%(2점차분 −0.01%)로 하네스 이빨 확인.
- **시뮬로 미검증(실기 대기) = U1~U5**: UM=3에서 SE→CA[70] 실주입 여부, 전압지령 실신호명·실기 BH 업로드 포맷(잠정 파서 교체 필요), CL[4] 단위, MO=1→SO=1 지연, CA[42..44] 실값. E4 verify_run은 정직 스텁.
- **다음(사용자 선택 확정 2026-07-12)**: **(b) GUI 배선 먼저 → 그다음 (a) 실기 감독 하 1회.**
  - GUI 계약: AutotuneParams에 `progress_fn(code,detail)`(no-op 기본, phase 경계 emit: P0/VALIDATE/SNAPSHOT/ENABLE/MEASURE_R/MEASURE_L/DESIGN/DONE) + `cancel_fn()->bool`(_sleep 청크마다 폴, True면 AbortError→§6 abort체인) 추가. 둘 다 예외가 튜닝을 죽이지 않게 가드. 기존 30테스트 불변, 신규 abort/progress 테스트 추가. → fable-driver 위임.
  - main.py: DriveWorker에 `autotune` job + progress/cancel/result 시그널, Tuning 페이지 Run(연결시 활성)+확인다이얼로그(통전 경고·모터 고정 확인)+6단계 라이트 라이브+Abort 버튼+결과 KP/KI/PM/R/L 표시+Apply(SV)/Discard. --smoke 및 헤드리스 목-드라이브 통합 스모크로 검증. 무인 통전 금지(Run은 사용자 클릭+확인게이트에서만).

### GUI 배선 완료 — GREEN (2026-07-12)
- 모듈 훅(fable-driver): AutotuneParams에 `progress_fn(code,detail)`·`cancel_fn()->bool` 추가. progress 예외→evidence(GREEN 유지), cancel 예외→warnings(YELLOW 강등), cancel True→§6 abort. **pytest 34 passed**(기존 30+신규 4: progress 순서·cancel abort 인덱스·progress예외 완주·cancel예외 무시).
- GUI(main.py, 메인세션): DriveWorker `autotune`/`autotune_apply` job + started/progress/result/applied 시그널 + `_run_autotune`(sleep_fn=msleep, progress_fn/cancel_fn→Qt 시그널). Tuning 페이지=Run(연결시 활성)+통전경고 확인다이얼로그+6단계 라이브 위저드(●◆○)+Abort+측정 R/L/PM+KP/KI+Apply(확인후 SV). 페이지 idx=3.
- **독립검증 GREEN**: `--smoke-autotune` 신규 16/16(핸들러→표시, RED가 Apply 끄기 포함) + 워커글루 SimDrive 통합(P0..DONE 스트림·KP/KI 일치) + main --smoke exit0 + --smoke-feedback GREEN(무회귀) + import OK.
- **실버그 1건 수리**: RED/abort 결과가 직전 GREEN의 Apply 버튼을 켠 채로 남김 → 상태 in (GREEN,YELLOW)로 게이팅. (+ 잘못된 자체단언 1건 정정.) 함정: `smoke_at` 플래그만 만들고 디스패치(`if smoke_at: return`) 누락 → app.exec() 행 → faulthandler로 라인 특정해 수정.
- **실기 1회차(2026-07-12, 감독 하) = RED at P2, 통전 전 — 모터 안 돌음(안전).**
  - **실기 확정치(결과 JSON)**: **TS=100µs**(→ f_max=0.125/TS=**1250Hz**), CL[1]=21.2132A(=15Arms×√2), PL[1]=70.7107(=50Arms×√2), MF=0, CA[18]=65536, UM=5, **드라이브 현재 KP[1]=0.07177·KI[1]=812.93896 = EAS 오라클과 자릿수 일치(실기 확증)**.
  - **RED 근본원인**: 기본 여진 주파수 하드코딩 (800,1600)Hz 중 1600 > 1250 한계. 시뮬 TS=50µs(한계2500)에선 안 걸림 → 실기 첫 노출. **수정: freqs를 측정 TS에서 자동 산출**(f_max 아래) → fable-driver 위임.
  - 아직 미도달(P2 이전 중단이라): U1(UM=3 SE 주입)·U3(전압신호명·BH 포맷)은 주파수 수정 후 재실행에서 확정. 무인 금지.

### 주파수 자동산출 수정 — GREEN (2026-07-12, fable-driver)
- freqs_hz 기본 None→측정 TS에서 파생(`derive_freqs`: f1≈0.32·fmax, f2≈0.64·fmax, <fmax, L관측성 가드). 실기 TS=100µs→(400,800)Hz. **pytest 37 passed**(34+3). 명시 초과-주파수 RED는 보존. **다음 실기 관문 예상=U3**(실기 링크에 recorder_signals() 없어 P4에서 정직한 RED "레코더 신호목록 확보 실패").

### Encoder Maintenance 추가 + Soft Zero 재라벨 — GREEN (2026-07-12)
- 실기 확증(펌웨어 노트): **TW[18]=<값>** 단일회전 절대위치 리셋(EnDat 임의값·0=영점, 타센서 0만/EC=99), **TW[20]=1** 소켓1 에러리셋. **TW[19]** 다회전 리셋=`TW[19]=0`(최선근거, 값 0 vs 1 문서 100%확정불가 → 앱이 명령원문+드라이브응답 표시로 실기서 즉시 확인). **PX=다회전×counts+단일회전이라 완전영점=TW[18]+TW[19] 둘 다**(사용자 실증).
- main.py: Feedback 'Encoder Maintenance' 버튼→다이얼로그(Set Datum Shift 입력 / Reset Multi-turn / Reset Errors / ▶Zero Position=TW[18]+TW[19] / SV선택). 워커 encoder_maint job=MO=0게이트+명령별 응답표시+PX갱신. Motion PX=0→**"Soft Zero(세션·증분용)"** 재라벨(절대영점은 Encoder Maintenance로 안내).
- 검증: 신규 `--smoke-encoder` 7/7 GREEN + 회귀 autotune/feedback/main 전부 GREEN + import OK. 앱 재기동됨.
- **다음(사용자)**: (a) Encoder Maintenance로 Zero Position 실기 시험(PX→0? 상태줄 응답·EC=99 여부 보고) · (b) Auto-Tune 재실행(P2 통과, U3 RED 예상). 무인 통전 금지.

### Encoder Maintenance 실기 검증 완료 — GREEN 확정 (2026-07-12)
- **영점 절차 실기 확정**: **TW[18]=0**(단일회전 절대위치 영점, 각도 287.3°→0.0°) + **TW[19]=1**(다회전 영점). 둘 다 해야 PX=0 (PX=다회전×65536+단일회전). Zero Position 버튼이 둘을 순차 전송.
- **TW[19] 값 실기 확정**: `TW[19]=0`은 드라이브가 **거부(Drive error 21)** → **TW[19]는 값이 아니라 소켓 인자**(TW[20]=1과 동일). **TW[19]=1**(소켓1=우리 피드백 소켓)이 정답. TW[18]만 값(위치), TW[19]·TW[20]은 소켓.
- **영구성 실기 확정**: Encoder Maintenance 영점(TW[18]+TW[19]) → **전원 off/on 후에도 PX=0 유지**(SV 불필요, 엔코더 비휘발성 메모리 직접기록). 대조로 **Soft Zero(PX=0)는 전원 후 절대위치 −2,071,933,877로 복귀=휘발성**. 이걸로 "Soft Zero vs datum" 차이 완전 실증.
- 코드: main.py Reset Multi-turn/Zero Position = TW[19]=1. encoder_maint_result 시그널→영구 팝업(명령별 드라이브응답 표시). `--smoke-encoder` 9/9 GREEN. MRG GREEN.
- **남은 것 = (b) Auto-Tune 재실행**(P2는 (400,800)Hz로 통과, U3=레코더 신호목록 RED 예상). 무인 통전 금지.

### 실기 오토튠 2회차 RED at P4(U3, 통전 전 안전) + 레코더 API 완전 그라운딩 (2026-07-12)
- 실기: P2 통과((400,800) 파생), **P4 RED "레코더 신호목록 확보 실패"**, snapshot_path=None=통전 전 안전.
- **`docs/recording-api.md` 참조**(fable-reader CR/FW + 메인 오프라인 DLL 리플렉션). 요지:
  - 잠정 BH경로 = 버그 확정(BH는 비트필드 `BH=(1<<bit)`, hex-binary 헤더). **폐기하고 .NET 경로 사용.**
  - .NET: `comm.PersonalityModel.SignalsMetaData`=`Dict<int,RecordingSignalSetup{Name,SignalIndex}>`=신호목록. `GetRecordingObject()`→`ConfigureRecording(RecordingSetup{TimeResolution,RecordingLength,SignalData,TriggerSetup{SetupType=Immediate}})`→`StartRecording()`→`GetRecordingStatus()`폴(REnd)→`UploadRecordingData().Data`=`Dict<int,Double[]>`(물리 double). `CreatePersonalityModel(path,out err)`.
  - 실기 전용 미확정: CreatePersonalityModel 업로드거동·전압지령 신호 존재(U3본체)·dt.
- **레코더 .NET 통합 완료 — GREEN (2026-07-13)**: elmo_link `recorder_signals()`(PersonalityModel.SignalsMetaData)+`record()`(GetRecordingObject→Configure/Start/Status REnd폴/UploadRecordingData.Data=물리double) 신설. 오토튠 `_record`=link.record() 단일경로, 레거시 RC/RG/BH+`_parse_bh` **완전삭제**(트립와이어). **독립검증**: pytest **39 passed**, 오프라인 `_reflect_recorder()` **11/11**(실 DLL), 스모크 전부 GREEN, 파이프라인 수치불변(TS50 R+0.004%/L−0.774%·TS100 R+0.009%/L−1.109%). 문서결함 정정: 타입 네임스페이스 `.Recording`/`.Personality`(리플렉션 실측, `docs/recording-api.md` 반영).
### 실기 3회차 RED at P4 → 근본원인·해법 실기 확정 (2026-07-13, 읽기전용 진단)
- **원인**: `CreatePersonalityModel(path,out err)`은 **기존 XML을 파싱만**(업로드 X) → 파일없어 LibEC=8 실패. personality를 올리는 `comm.UploadPersonality(path,out err)`(comm이 구현함) → `IUploadDownloadModel.Start(out err)`가 **LibEC=9 "No Callbacks Registered"** — **OnStart/OnProgress/OnFinish/OnFailed/OnCancel 이벤트 5개를 Start 전에 += 등록해야** 작동.
- **확정 흐름**: UploadPersonality(path)→5이벤트 핸들러 등록→Start(out err)→`OperationStatus`(enum UNDEFINED/STARTED/FINISHED/FAILED/PROGRESSED/CANCELED) FINISHED 폴→CreatePersonalityModel(path)→`PersonalityModel.SignalsMetaData`(**254개**). 업로드된 XML은 `lib_net/personality_model.xml` 캐시(재접속 시 재업로드 불필요).
- **U3 답(실기 신호명)**: 전압=**A/B/C/D Voltage**, 전류=**Active Current [A]**(+Reactive), 전류지령=**Current Command [A]**/**Total Current Command [A]**. 정규식이 전압 4개·전류지령 2개 잡음 → **매핑 정밀화 필요**. 전압은 UM=3 SE여진에서 어느 채널이 인가전압인지 실기 특성화로 확정(4채널 다 녹화해 여진주파수 성분 대조).
- IDriveErrorObject: ErrorCode/LibraryErrorCode/ErrorDescription/LibraryErrorDescription.
- **다음(fable-driver)**: elmo_link `_personality()`=업로드+콜백 흐름(캐시우선)+실패시 last_error 노출+신호목록 JSON 덤프. autotune `_resolve_signals` 실기이름 매핑(current=Active Current [A], ref=Current Command [A]; voltage는 4채널 녹화 후 실기 특성화). 그다음 감독 실기.

### 실기 5회차: 파이프라인 완주(전 배관 작동)·R/L 135~170배 오차 → 원인·보정 확정 (2026-07-13, fable-physics)
- **완주**: Init·Current ID·Current Design 3단계 GREEN, YELLOW(전압 잠정). 실물 모터 통전 측정 성공. 안전(Apply 안 함, 게인 EAS값 유지).
- **원인 3중첩(확정)**: 전압 A/B/C/D Voltage = **레그 PWM 듀티 카운트**(상전압 아님, mid=3750=0V, D=유휴상수). (a)스케일 미적용 (b)raw 단일채널=상전압×3/4(SVM 공통모드) (c)위상폐기(abs→L +45%편향). 전류는 정상(amps).
- **드라이브 게인계=ph-ph 확정**: KP=ω_c·L_pp=0.071757 vs 실측 KP[1] 0.07177 (−0.018%). 오토튠 산출목표=R_pp·L_pp.
- **보정식**: `v_phN=v_A−mean(A,B,C)`(오프셋·공통모드·3/4 동시제거), `R_pp=2·Δv̄_phN/ΔI`, `L_pp=2·Im(V_phN(f)/I(f))/2πf` median(복소, abs금지). **스케일=KP기준 in-situ 캘리브레이션**(C(s)=KP(s+2πKI)/s, Vbus·FS 가정우회) + **DC Bus Voltage[7] 채널 교차확인**.
- 보정 후 예상 R_pp~0.12-0.14·L_pp→35.7µH수렴. R잔차 +17.5%는 **실 Vbus 1독**으로 (Vbus≠48 vs 케이블·FET 기생R) 판별. 폐루프 게인 역피팅이 진짜 L_pp≈32.8µH(명판근처) 독립시사.
- **다음(fable-driver 구현중)**: 보정식+복소Z+스케일2경로+DC Bus채널+시뮬목 갱신. 그다음 감독 실기 6회차(R/L 오라클 대조). 실기전용 미확정: CreatePersonalityModel 업로드거동·전압신호 존재·dt·Data키=SignalIndex. 신호명이 정규식(`voltage`&!`bus`/`IQ|active current`/`current command`)과 다르면 RED+덤프→매핑조정. 무인 통전 금지.

## 상태
- 2026-07-12: 범위 확정 → 통신 스파이크 GREEN(Path A) → **화면1(연결+Single Axis Motion 대시보드) 완성·실기 GREEN**.
  - 앱 정체성: **AngryYJH Control** (Made By 여재현), 테마 = QDD 아노다이즈드 네이비(`theme_qdd.py`),
    macOS 상단바(프레임리스+트래픽라이트), SPG 로고, 실제 앵그리버드 이미지(`angry_bird.png`, 흰배경 제거).
    테마 스왑: `AYJH_THEME=qdd|angrybirds|amber`.
  - `elmo_link.py`: connect/command(모션가드)/read_telemetry(PX/VX/PE/IQ/MO) 실기 GREEN. VR/VP/VB 그라운딩 완료.
  - Zero Position(PX=0) 버튼: CR에서 Read/Write·비모션 확정. `DriveWorker.send_once` 큐로 전송.
  - 실기: 자동포트탐지(COM3), VR='Twitter 01.01.16.00 08Mar2020B01G' 일치.

## 다음 (화면2·3) + fable-reader 위임
- 화면2 = **Motor Settings**(영상값: Peak 50Arms·Cont 15Arms·MaxSpeed 3600·극쌍 16·R 0.119Ω·L 0.0357mH·Ke 0·Motor Type CA[28]).
- 화면3 = **Automatic Tuning 6단계 마법사**(Init→Current ID→Current Design→Commutation→Vel&Pos ID→Vel&Pos Design). **주의: 튜닝은 모터를 회전시킴 = 모션. 안전확인 게이트 필수, 무인 발사 금지.**
- 화면4 = **Feedback Settings**(엔코더/센서 선택) — 사용자 요청(2026-07-12): EnDat 하나만이 아니라 홀·BiSS·증분·리졸버·sin/cos·아날로그 등 드라이브가 지원하는 **모든 센서 타입을 personality 기반으로 자동 열거**. 현 드라이브 피드백 = Serial Absolute EnDat 2.2 Port A(19bit HW/16bit SW). 센서선택 = CA[41–45] 계열. UI는 스크린샷 하드코딩 금지, 지원목록 동적.
- **열린 질문(→ fable-reader, `docs/command-reference.txt` 330p):**
  1. Motor Settings 8필드 각각의 읽기/쓰기 명령·파라미터(예: MC=Maximum Current, CL=Current Limit 확인됨; 극쌍/R/L/Ke는 CA[] 배열 어느 인덱스인지).
  2. Automatic Tuning을 명령으로 트리거하는 방법·시퀀스(EAS 6단계 대응), 각 단계가 모션을 유발하는지, 사전 안전조건(MO상태·전류제한).
  3. 각 명령의 access(RO/RW)·범위·단위.
  - 수용기준: 필드→명령 매핑표 + 튜닝 트리거 시퀀스 + 모션유발 표기. 불확실하면 "미확정"으로.

### 실기 6회차: 물리보정 검증 성공 — R/L 135배→오라클 ±18% (2026-07-13)
- **R_pp=0.0981Ω(−17.5%)·L_pp=42.31µH(+18.5%)·PM69°** (in-situ 스케일 표시). 지난 16Ω/6175µH에서 대폭 수렴 = 중성점차감·복소Z·스케일 보정 실물 검증됨. YELLOW(스케일 미확정).
- **실 Vbus=48.46V**(레코더[7] 실독) → 48 가정 맞음, Vbus는 잔차원인 아님.
- **스케일 단서**: s_vbus=0.006461. in-situ 400Hz=0.006628(Vbus와 2.6% 일치!)·800Hz=0.002294(2.9배 벗어남, z_model_re 음수=비물리 고주파 루프모델오차). → **Vbus스케일이 진값, 800Hz in-situ 폐기 방향**. Vbus스케일 R_pp=0.142(+19%)=기생저항(케이블·FET ~23mΩpp) 가능성.
- **fable-physics(aa17f369) 재판별 중**: 최종 스케일식·R기생처리·L 재검산·GREEN 기준. 그다음 코드반영→실기 7회차.
- **미결 α**: KI 계수 1.2705→2.541(EAS KI 812.94 매칭, 현재 406=절반). R/L 확정 후 결정.

### 실기 9회차: G0 실기확정(FS=7500) + G5만 실패 (2026-07-13)
- **G0 PASS 실기확정**: XP[2]=2 실독→FS=150MHz·TS/XP[2]=**7500**. WS[53]=0.02578·WS[54]=7200·WS[56]=150·WS[57]=7050. 스케일 s=Vbus/7500=0.006461 **문서+실측 완전확정**.
- 측정 불변: R_pp 0.1502·L_pp 41.29µH·KP 0.083·**KI 812.87(EAS −0.0087%)**·PM 59.3. G1′/G2/G3/G4 PASS.
- **G5(루프게인) 실패**: rho_meas/rho_pred=1.92/1.84/1.76/1.72(감소), 측정 크로스오버 638Hz vs 예측 280Hz. 드라이브 실효루프게인이 파라미터-KP 예측의 ~1.9배 — 드라이브 내부 KP→실효게인 인자로 추정(R/L 무관). fable-physics 판별 중(advisory 강등 vs 인자수정).
- **레포 푸시 완료**: 비공개 `Fable5-Elmo-Gold-AngryYJHControl`(commit 468b126). README+brief+압축전사+코드.

### 실기 10회차: 6게이트 전부 PASS(G5픽스 성공) + B3 리플 아티팩트만 (2026-07-13)
- **G0/G1′/G2/G3/G4/G5 전부 PASS** — 전류루프 물리 검증 완료. R=0.136(식음)·L=41.60µH·KI=812.87·PM54.9.
- 유일 YELLOW = **B3(_verify_recorder_iq)**: 레코더 창평균IQ 2.121A(std0.083=3.9%리플) vs 단일폴링 2.236A =5.1%. 단일폴링이 리플피크 캐치, 폴링∈[평균±2σ] → 실제 일치·측정 무영향. → **B3 리플인식 수정**(fable-driver): 폴링∈[rec min,max] 또는 |Δ|≤max(5%,3σ). 임계확대 아님.
- 그다음 실기 11회차 → **전류루프 첫 실기 GREEN 예상**(6게이트+B3). Apply 또는 Phase 2로.

### ★ 실기 11회차: 전류루프 첫 실기 GREEN — Phase 1 완성 (2026-07-13) ★
- **STATUS GREEN, 경고 0, 6게이트(G0/G1′/G2/G3/G4/G5) 전부 PASS.** R_pp=0.1392Ω(터미널)·L_pp=41.62µH·KP=0.0837·KI=812.87(EAS −0.0087%)·PM55.7°·크로스오버362Hz·s=Vbus48.41/7500.
- 11번의 감독 실기로 실물 관문 전수 통과: 여진주파수→personality업로드(콜백)→레코딩키(위치)→전압단위(레그PWM카운트·중성점차감·복소Z스큐)→스케일(Vbus/FS문서확정 G0)→게이트(G1폐지·G5루프게인·B3리플). 자체 오토튠이 EAS 규칙을 실측 R/L에 적용(KP비=L비, KI일치) 확증.
- **다음(사용자 결정)**: (A) Apply(우리 게인 KP0.0837/KI812.9 → 드라이브+SV; EAS 0.0718 대비 +16%는 실측 L 반영, 안 눌러도 EAS게인 유지) · (B) Phase 2(커뮤테이션·속도/위치, 회전) · 미확정 5건 전부 GREEN 비차단(명판L·기생·SE노드·−3.5%잔차·WS[53]).

## 신규 목표 (2026-07-13): Phase 2 — 커뮤테이션 + 속도/위치 튜닝 (구동)
전류루프(Phase 1) 실기 GREEN 완성 후, 사용자 선택으로 Phase 2 착수. EAS 6단계 중 4~6단계
(Commutation → Vel&Pos Identification → Vel&Pos Design). **모터 실제 회전 수반 — 안전 한급↑**.
- 방식: 그라운딩→SPEC설계→구현→감독실기(전류루프와 동일 규율).
- 재사용: .NET Drive Recording + 측정 인프라(personality/record/스케일)가 그대로 이월 —
  회전 중 속도·전류 캡처로 기계플랜트(관성 J·마찰 B) 식별.
- 드라이브 현재 vel/pos 게인(EAS): KP[2]=0.0001·KI[2]=10.7·KP[3]=85.2. 우리가 J·B 실측→재산출 목표.
- 안전: 속도제한·회전범위·abort·중감독. 축이 자유회전 안전해야 함.
- 착수: fable-reader로 Elmo 속도/위치·커뮤테이션 명령 그라운딩(무위험).

### Phase 2 그라운딩 완료 (fable-reader, 2026-07-13) — docs/command-reference.txt 1.406
- **F1 UM 무변경**: UM=5 그대로 TC→토크·JV→속도·PA/PR→위치 자동강제. 모드변경 불필요(안전).
- **F2 커뮤테이션 자동**: CA[17]=5+CA[7], MO=1시 무동작 커뮤. EAS 튜닝됨=검증만(회전0). (옵션 스테퍼정렬 SC[1..5]=±11.25°기계.)
- **F3 J/B 프리미티브 없음** → record()로 자체측정(CR도 FF[1]식별법으로 지지). 핵심=K_a≡dv̇/dI[cnt/s²/A](명판 Kt불요).
- **식별법 A(권장)**: UM=5, TC=±I0(5~10%CL[1]), record(Active Current idx10·Velocity idx1), K_a=(v̇₊−v̇₋)/2I0(±상쇄 마찰제거). B=정상상태 I/v 또는 코스트다운 지수피팅. **후보B**=JV속도스텝(폐루프·최다보호). **후보C**=SE여진(EAS방식·Stop Manager우회 주의).
- **게인**: KP[2] A/(cnt/s)·KI[2] Hz(영점2πKI 추정)·KP[3] rad/s(위치대역폭). 설계식 EAS내부→역설계(K_a·B+케스케이드분리비 실측+PM게이트, Phase1 α패턴).
- **★최우선 실기확인 GS[2]=0**: ≠0(예66)이면 KP[2]/KI[2]/KP[3] 무효·KG[]테이블 지배. EAS표시=KP[2..]일치라 0개연 높으나 확정필요.
- **안전**: 기본리밋 전부 사실상OFF(VH[2]2e9·ER[2]1e8·ER[3]1e9·SD1e9)→매세션 명시설정. 급정지 ST(SD감속)→MO=0(코스트). MO=1후 SO=1폴. 종료 TC=0/ST→MO=0. HL[2]/LL[2] 문서모순(Reserved인데 참조)→실기질의.
- **읽기전용 사전세트(무회전)**: GS[2]·HL[2]·LL[2]·HL[3]·LL[3]·VH[2]·VH[3]·VL[3]·ER[2]·ER[3]·SD·AC·DC·SP·SF·CA[7]·CA[16]·CA[17]·TR[1..4]·WS[28]·WS[55]·FF[1]·FF[2]·PO. 다음: 이 프로브→SPEC설계(fable-physics)→구현→감독회전실기.

### Phase 2 읽기전용 프로브 확정 (2026-07-13, 회전0)
- **GS[2]=0 확정** → KP[2]=7.896e-5·KI[2]=10.7·KP[3]=85.2가 실효 vel/pos 게인(오라클). GS[0]=0 GS[1]=100.
- **루프주기 전부 100µs**(TS·WS[28]속도·WS[55]위치). HL/LL 실존·전부0(과속리밋 꺼짐). ER[2]=1e8·ER[3]=1e9(추종오차 huge→조일것).
- VH[2]=3,932,160(3600rpm)·AC=DC=SD=1e6·SP=4.44e6·VH[3]=VL[3]=0(위치범위 설정필요)·TR[1..4]=100/20/100/20.
- 커뮤: CA[7]=438·CA[16]=0·CA[17]=5(검증만). FF[1]=1.726e-7 A/(cnt/s²)·FF[2]=1. CL[1]=21.21·PL[1]=70.71·MC=140. UM=5·MF=0.
- 프로브 스크립트: `diag_phase2_readonly.py`(재사용 가능). **다음: fable-physics Phase2 SPEC(K_a/B 식별·PI설계·안전·게이트) → fable-driver 구현 → 감독 회전실기.**

### Phase 2 SPEC 완성 (fable-physics) + 구현 착수 (fable-driver, 2026-07-13)
- SPEC=`docs/autotune-velpos-spec.md`. **핵심 발견: FF[1]=1.726e-7=1/K_a**(EAS 기계플랜트 지문) → EAS게인 역설계: ω_cv=0.04575/TS·KP[2]=ω_cv/K_a·KI[2]=ω_cv/(2π·6.805)=10.70·KP[3]=ω_cv/5.369=85.2 (오라클일치). 풀모델 속도PM67.6°·위치PM81.1°=건전.
- 식별: K_a=dv̇/dI(UM=5 토크±펄스, ±상쇄 마찰제거, 4경로 교차), B·I_c(JV 정상상태). 안전: I0=0.1CL[1]·Tp프로브사이징~1rev/런·SW가드1200rpm·abort(TC=0→MO=0/JV=0;ST→MO=0)·리밋명시. 게이트 G0~G5. 인프라: record()→record_start+record_fetch 분리.
- 구현 위임(fable-driver): autotune_velpos.py + T3시뮬 테스트 + record분리, main.py/Phase1 불변, 헤드리스만. 그다음 GUI배선→감독 회전실기(A1 FF[1]=1/K_a 실측확증이 최우선 실기목표).

### Phase 2 실기 1회차 + 범용화 요구 (2026-07-13)
- 실기: 커뮤테이션 통과·모터 회전, 식별 RED "속도대 매칭창 부족(n1=0)". 안전 abort 정상(MO=0·MF=0). 프로브 k_a≈46,000 vs EAS암시 5.79e6=**125배**.
- **정정(사용자)**: EAS로 **감속기(1:30 유성) 달고** 오토튜닝 잘 됨 → EAS FF[1]·게인=loaded값. 즉 **125배=우리 K_a 측정오차**(추가관성 아님, Phase1 전압-단위 동형). 46,000 진짜면 EAS 루프 0.58Hz=비작동인데 "잘됨" → 진짜 K_a~5.79e6, 우리측정 틀림.
- **★범용화 요구(사용자)**: 나중에 다른 모터·**맨 모터 단품**도 문제없이 튜닝되게. → ①단위정확(어떤모터든 K_a정확) ②**적응형 펄스사이징**(프로브 K_a로 본펄스 조절, 가벼우면작게·무거우면길게, 상한넓게 — 지금 800rpm/0.3s clip 고정이 실패원인) ③**검증 범용**(자기일관+물리+안정도+F2 스텝응답, EAS오라클 하드의존 금지). EAS=이 드라이브 검증용 advisory. 알고리즘=파라미터구동 범용, 실기검증=이 감속기시스템(필드홀드아웃).
- **판별경로**: 125배=속도단위 vs record dt — 같은기록 **∫v·dt vs ΔPosition(counts확정)** 교차확인으로 확정(G1d가 노렸으나 RED가 선행). fable-physics 재분석중(정정전제)→fable-driver 단위/dt수정+위치교차확인+원배열덤프+적응사이징+오라클범용→재측정.

### B1.5 UNIT-DIAG 구현 완료 — GREEN (2026-07-13)
- SPEC §9 반영: 진단런(TC+0.5A/80ms·TR=1·4채널+VX폴)→판별식 3개(g dt·s 속도스케일·K_a Position2차피팅=속도불문 최종심판)→판정표(속도스케일 보정/dt/토크미인가RED)→하드게이트→본펄스. 매칭창 [30%,70%] 상대구간. 원배열 evidence.
- **독립검증**: pytest 90(Phase1 60무변경+Phase2 26+4), 5스모크 GREEN. 재현: 정상 K_a+0.01%·속도1/125 검출→K_a복원−0.01%(YELLOW U-P9)·토크미인가 RED. → 실기 진단런 1회(0.08s·출력≤2°)로 125배 정체 확정.
- **모터 교체 진행중(사용자)**: 같은사양+감속기 다른 물리유닛으로 교체, EAS 재튜닝 먼저(커뮤 CA[7] 유닛별). 우리앱 정지·COM3 비움. B1.5는 드라이브레벨이라 새 모터에도 적용. 복귀시: 앱재기동→Connect→설정확인→Phase1/2로 새유닛 측정(범용성 실증, EAS새게인=새오라클).

### Phase 1 정렬 견고화 — 헤드리스 GREEN (2026-07-13, fable-driver, 실기 미접촉)
- **근본원인(fable-physics 확정) 수리**: 실기 "모션 감지 |dPX|=2191>364" = i1만으로 정렬·래치 후 측정창에서 i2 인가 시 stiction 돌파 스냅(정지≠정렬). 수정 = **B4 고전류 사전정렬(fix b)**: px_ref 래치 전에 TC를 **i2까지** 램프해 스냅 소진(준정적 보장) + **i1↔i2 래칫(fix c, 최대 3회)** 사이클 종단 |ΔPX|≤θ_abort 수렴 시 즉시 게이트 조임(px_ref=종단PX·tol=θ_abort), 미수렴→정직 RED "정렬 미수렴". 사전정렬 램프 구간만 PX가드 **1.5극피치=1.5·CA[18]/CA[19]**(실기 4681cnt)로 완화, MF/LC 가드·측정창 θ_abort=364는 불변.
- **부수 수리**: (i) :894 하드코딩 11.25°(=180/16극쌍) 폐기 → 반극피치=CA[18]/(2·CA[19])×1.2, CA[19] 판독불가시 16 가정+경고(YELLOW). (ii) abort A3(TC=0)의 err58 "Servo must be on"은 A1(MO=0) 성공 시 예상거동으로 steps에 기록·경고 제외(순서 A1→A2→A3 불변, SimDrive도 실기처럼 MO=0에서 TC 거부하게 실화). (iii) 사전정렬 스텝별 (TC,PX) 트레이스를 evidence["prealign"]에 기록(다음 실기 런 δ₀·텀블 실측용). (iv) 신규 progress 코드 ALIGN(ENABLE↔MEASURE_R 사이, main.py 스테이지1 매핑).
- **독립검증 증거**: pytest **97 passed**(기존 90 무회귀+신규 7: stiction 스냅 사전소진→GREEN·완화가드 초과 RED·래칫 미수렴 RED·CA[19] 스케일링 16vs21·CA[19]폴백·err58 강등·nominal 1사이클), `--smoke-autotune`·`--smoke` GREEN. 실기 기하(CA[18]=65536·p=21) 교차검증: i1=5.30A/i2=10.61A/θ=364/완화 4681cnt = 계약 동결수치 재현; 끝까지 안 움직이는 로터(stiction>i2)도 GREEN·R/L 무영향(−0.04%/−1.15%) 불변식 확인. 스펙 문서 §0/§3.1/§5-6/§7 B4/§8 갱신.
- **하드닝 3건(fable-critic findings, 2026-07-13)**: ① CA[18] 판독불가/0→모션게이트 inf 비활성을 경고로 명시(YELLOW, 침묵 비활성 금지) ② 사이클 PX 판독불가(dpx=None)→수렴 아님(캡→RED "무모션 증거 확보 실패") ③ 수렴 사이클 내 가역 변위 dev_max>θ_abort→경고만(감속기 컴플라이언스 false RED 방지). pytest **100 passed**(+3: CA[18]=0 YELLOW·PX비숫자 RED·탄성변위 YELLOW)·`--smoke-autotune` GREEN·스펙 §8 갱신.
- **다음(실기, 사용자 감독)**: 재조립 유닛 첫 런 = 위험 케이스였던 시나리오 그대로 → 사전정렬 트레이스(evidence["prealign"])로 실제 δ₀·스냅 파형 확인. 무인 통전 금지.

### Phase 2 브레이크어웨이 램프 + g wall-clock 수정 — 헤드리스 GREEN (2026-07-13, fable-driver, 실기 미접촉)
- **배경(fable-physics 실기판정)**: 125×=단위오류 아님(속도스케일 s≈1 실측), 46,000=probe 0.5A가 감속기 정지마찰(0.5A 무이동/2.12A 이동)을 못 넘어 stiction에 갇힌 저전류 노이즈 → B1.5 "기계구속" RED는 정직했으나 축은 튜닝가능.
- **구현 1(g 타이밍 버그)**: UNIT-DIAG 펄스 기준시간이 명목 80ms인데 실제 벽시계 ~125ms(poll_sleep의 VX 직렬왕복 +56%) → 舊 g=0.08/(N·dt)=0.641을 dt계수로 오채택할 위험. **수정: T_host=TC 쓰기 전후 clock_fn 브래킷 중점 실측**(AutotuneVPParams.clock_fn 신설, 기본 time.monotonic), g·후반창·g_corr 전부 실측 사용. 물리 하한 max(브래킷,명목)으로 clock 미주입 환경 자동 폴백(`t_pulse_src` evidence 명시) — main.py 스모크 무수정 통과. 시뮬은 clock_fn=sim.t 주입(tests `_params`).
- **구현 2(적응형 브레이크어웨이 램프, B1.4 신설)**: TC 0→0.2·CL[1] ≤2s 램프(30ms 폴), |ΔPX|>400 ∨ |VX|>3000 **2연속** 검출 즉시 TC=0·**i_ba 기록**(B·I_c 선험치, `jv.i_ba_prior_a` 교차참조·게이트 아님). **probe=clip(1.5·i_ba, probe_i_a, 0.2·CL[1])** → UNIT-DIAG(i_diag=max(0.5A, probe))·B1 프로브에 사용. 캡 무이동시 IQ 분기: 토크 실인가→정직 RED "축 구속(클램프/브레이크?)", IQ≪캡→UNIT-DIAG 토크미인가 분기 위임(MO/SR/MF/LC 로그 보존). 파라미터 6종(ramp_frac/ramp_time_s/poll_dt/detect_dpx/detect_vx/breakaway_k). 신규 progress 코드 BREAKAWAY(main.py 스테이지4 매핑).
- **독립검증 증거**: pytest **104 passed**(직전 100 −1 대체 +5 신규: (a)저마찰 i_c=0.2 vs 고마찰 1.2에서 적응 probe 상이+i_ba∈(I_c, I_c+0.35] 기록, (b)i_c=6.0 캡 무이동→RED "축 구속"+IQ증인, (c)스트레치 sleep×1.5625+정확 clock에서 T_host≈125ms·g≈1·舊식 0.64 아티팩트 재현 확인, (d)i_c=1.2에서 적응전류로 로터 실이동·위치기반 K_a 게이트 통과·s/g 보정 0(125× 없음)·K_a ±2%, +舊 RED 케이스 i_c=0.6 이제 튜닝됨 고정). `--smoke-velpos`·`--smoke` GREEN. K_a/B/I_c 수식·G0~G4 게이트·abort 체인·1200rpm 가드 불변. 스펙 §10 신설.
- **테스트 계약변경(명시)**: test_static_friction_too_high_red(i_c=0.6→RED) 폐기 → test_axis_clamped_at_cap_red(i_c=6.0, 캡 초과 정지마찰만 RED) — 계약이 요구한 설계변경("서브캡 stiction은 튜닝 대상")의 직접 귀결, test_previous_stiction_red_case_now_tunes로 의도 고정.
- **하드닝 5건(fable-critic 2차, 2026-07-13)**: ① 램프 검출을 누적 |PX-PX0|→**폴 간 델타 2연속**으로(백래시/와인드업 단발점프가 i_ba 과소래치→probe 과소→false RED 재발할 뻔한 실발동급 결함 제거) ② UNIT-DIAG **모션 조기종료**(|VX|>500rpm 즉시 TC=0, 적응전류+저동마찰의 1200rpm 가드 RED 방지)+각 TC 스테이지 앞 `_wait_rest` ③ 캡 무이동+IQ 판독불가→"토크 실인가" 허위표기 제거(UNIT-DIAG 위임) ④ 로터 이동+전류채널 미달(n_pulse=0)→명시 RED "전류채널 이상"(舊 내부예외 불투명 제거) ⑤ nominal-floor 분기 단전 테스트+`--smoke-velpos` need에 BREAKAWAY. pytest **109 passed**(+5: 와인드업 기각·조기종료 이빨(무종료시 가드초과 산술확인)·IQ위임·전류채널 RED·floor분기), 스모크 GREEN, 스펙 §10 하드닝 절 추가.
- **유격 오검출 수리 + 상향 이중방어(fable-physics 판정 반영, 2026-07-13)**: ① 램프에 **RAMP→HOLD-CONFIRM 상태기계**(검출 시 TC 동결·확인창 5폴: 누적>6000cnt ∨ VX 3연속=지속→i_ba 래치 / 2폴 정온=유격통과→lash_events 기록·램프 재개; 실기 i_ba=1.01A=유격통과였음, 진짜>1.52A) ② **UNIT-DIAG 상향 사다리**(무이동/유격착지 → ×1.5→×2.25→캡, 각 500rpm 조기종료 보호, 성공전류를 B1 프로브 하한 피드포워드, 캡 소진시만 정직 RED "축 구속/고마찰") ③ 마무리 실버그 2건: 유격착지 판별 분모를 레코드 ΔPos→**토크구간 내 pulse_travel**(저마찰 코스트가 ΔPos 지배해 진짜 도는 로터 false RED 나던 결함), `_wait_rest`를 VX+PX 이중증인 2연속으로 강화(30rpm≠정지 — 정지마찰은 정지출발만 게이팅) + 시뮬 쿨롱마찰 0교차 채터링을 Karnopp 클램프로 정정(sim 물리결함). GearLashSim(유격4500cnt+부하2.5A)·StictionRiseSim 신설. pytest **113 passed**(+4: 유격분류·지속/실속 분기·상향 회복·캡 소진 RED)·`--smoke-velpos` GREEN·스펙 §11 신설.
- **[HIGH] 본펄스 사이징 오더킬러 수리(fable-critic, 2026-07-13)**: 舊 본펄스 i0=0.1·CL[1] 고정(브레이크어웨이 결과 무시) + 모션부족 재시도 i0×2에 tp 미재산정 → 기어드유닛(정지마찰 2.5A)에서 56ms에 1200rpm 가드 돌파 = 다음 실기 확정 false RED였음(舊 수식 수기재현으로 확인). 수리: ① i0=max(min(frac·CL,0.2·CL), **검증된 mover 전류**=UNIT-DIAG 최종 성공 i_diag) ② `_size_tp`로 i0 변경마다 tp 재산정(양 재시도 경로 포함) ③ **본펄스 모션 조기종료**(|VX|>0.9·가드=1080rpm 컷, 캡처창 분석 계속·경고 가시화) — 정상 펄스(TP_MIN 클립 최악 1071rpm)는 미도달, 초고가속(폴당 상승>컷~가드 밴드)은 가드가 최종 방어. **검증 이빨: gear_lash 테스트의 i_pulse_frac=0.13 우회 제거→기본 0.10으로 GREEN**(실측 i0=3.894A·tp=50ms·v_pk=955rpm=여유 20%·K_a +0.04%). 가드 테스트는 고가속(i_frac=0.2)으로 재고정 + 저가속 초과=컷 생존 YELLOW 테스트 신설. pytest **115 passed**·`--smoke-velpos` GREEN·스펙 §11 갱신.
- **캡 상향 0.4·CL + UM=3 드래그 판별(fable-physics 확정, 2026-07-13)**: 실기 최종=0.2·CL 캡에서도 무이탈(i_ba>4.24A 확정, 커뮤 토크효율 저하 미배제). PART A=ramp_frac 0.4 지원(기본 0.2 유지, 자동 절대상한 0.4·CL P2 게이트·0.6은 승인전용 상수)+고전류 VX단독 10ms 고속폴+HOLD 즉시확정(|VX|≥300rpm 1폴)+**본펄스 i0=min(max(frac·CL,1.25·i_ba,mover),0.4·CL)** 천장해제+i_net(=i0−0.75·i_ba) 기반 tp+컷 0.75·가드/10ms(B1 프로브에도 컷)+UNIT-DIAG 캡 연동·후반창 적응+**windup_curve**(1/2/4/6/8A ΔPX·IQ+램프 레코더 Reactive/Field Angle 캡처). PART B=**UM=3 저속 드래그**(TC=6A·PA 512tick/erev·1erev/s·3rev/방향, 추종률 min≥0.9): 추종→RED "커뮤테이션 토크효율<70%, EAS커뮤/CA[7]", 슬립→RED "진짜 기계마찰 T_s>0.72N·m, 기계점검"; UM 이중복원(finally+abort A_um). 목 확장(CA[19]/PA/UM가드/um5_eff/PA-추종 물리). pytest **118 passed**(+3: 상향캡 i_ba=4.686 식별 K_a−0.02%·커뮤라우팅 follow=1.00·ramp_frac 0.6 사전RED; 가드 테스트는 JV경로로 재고정, 클램프 테스트는 기계라우팅으로)·`--smoke-velpos` GREEN·스펙 §12 신설.
- **PART B 거짓판정 봉쇄 5건(fable-critic, 2026-07-13)**: ① [HIGH-2] UM3 스윕을 CR 의미론으로 — **PA=int+매 스텝 BG**(:12471/:12476)+**초기 실효검사**(0.5 elec rev PX 응답<20% → `pa_effective=False` → **"판별 불가" 정직 RED**, 기계 단정 금지; VH[3]/HL[3]=0 소프트리밋·BG-PTP 프로파일러 속도 미보장이 근거), 슬립 문구 "슬립 또는 PA 미실효"로 ② [HIGH-1] PART B 발동을 **i_cap≥6A 게이트**로(_drag_route 통합, 미충족="판별 유보") ③ [MEDIUM] 폴 지연 가드밴드 — 펄스/HOLD/고속램프 인슬립 가드 MF/LC 생략(VX 단독)+컷 0.75→**0.6·가드**+사이징 타깃 0.8·컷(576rpm) 클램프+검출 시 |VX|≥300rpm 즉시 래치 ④ [LOW-1] 프로브 재시도 캡 0.4·CL 일관화·감액 금지 ⑤ [LOW-2] 사다리 소진도 게이트 충족 시 드래그 경유/아니면 판별 유보. 목이 **PA=BG에서만 실효**를 인코딩(BG 200회 실송신 증명). pytest **121 passed**(+3: BG무시→판별불가·부분슬립→정직 기계라벨·×2지연→컷 선개입 v_pk 793rpm·K_a −0.09%; 기본캡 게이트 테스트 재작성, 컷 테스트는 넷모델 불일치 시나리오로)·`--smoke-velpos` GREEN·스펙 §13 신설.
- **개정6: 가짜 i_ba 봉쇄(fable-physics 판정, 2026-07-14) — 처방 1~3+5 구현, 4 이월**: 실기 i_ba=1.33A=백래시 과도(HOLD 속도 89k→6k 단조붕괴). ① **지속 AND-규칙**: 누적>max(13000, 2×lash실측) AND vx_now≥0.5×HOLD최대(붕괴=즉시 실속·lash_events에 collapsed 기록·램프 재개; 확인창 15폴 연장은 비감쇠일 때만 — 과도는 이동 유계라 물리적으로 지속 불가). 소급: 실기 6k/89k=0.07→폴4 붕괴 ✓, 舊규칙은 지속 오판 재현 ✓ ② UNIT-DIAG 성공=**지속회전**(late_travel>max(200,3×60·i) AND 말미 위치미분 속도>3k — 269cnt 꿈틀 기각→escalation) ③ 사다리 소진 전 모드가 드래그 라우팅(가짜모션이 드래그 건너뛰던 실버그) ⑤ escalation 다점 windup+**K_a 절대 advisory**(FF[1] 함의 [0.1,10]× 밖 경고)+G1d U-P5 폐색. TransitDecaySim(실기 시계열 인코딩)·RiseJiggleSim 신설. pytest **124 passed**(+3: 붕괴→실속·진짜 i_ba=5.19·K_a−0.01% / 꿈틀→escalation·정직 RED / 소진→드래그 "판별 불가")·`--smoke-velpos` GREEN·스펙 §14. **처방4(프리로드+단방향 2레벨 K_a)는 이월** — C1/C2 코어 재작성이라 별도 구간; 이번 실기에서 i_ba>0.4·CL이면 본식별 미도달이라 그 다음 관문.
- **실기 전 보강 2건(fable-critic, 2026-07-14)**: ① D1 JV 무부하전류 게이트를 고정 0.10·CL→**max(0.10·CL, 1.2·i_ba) 적응형**으로(기어드 운전마찰 3A급이 K_a 식별 후 D1에서 런 죽이던 경로 — i_ba=정지마찰 상계가 운전마찰 상계; 검증: i_s=5/i_c=3 sim I_ss 3.03~3.10A가 舊 게이트 초과인데 통과·I_c=3.00 정확) ② UNIT-DIAG 말미속도를 2점 0.8ms 차분→**~10ms 최소자승 기울기**로(±2cnt 위치노이즈가 5000cnt/s로 읽혀 말기착지를 지속회전 오통과시키던 경계 — LSQ 실측 6cnt/s로 기각; LateLandSim 신설=travel 함정 통과+속도판정 단독 검증). pytest **126 passed**(+2)·`--smoke-velpos` GREEN·스펙 §14.1. MEDIUM-2(CA[18] 비례화)·처방4는 명시적 미변경(다음 개정 함께).
- **다중모터 CA[7] 오경보 제거(2026-07-14)**: expected_ca7 기본 438→**None**(값 게이트 스킵) — CA[7]은 모터별 커뮤값이라 하드코딩 무의미(드라이브 하나로 극쌍 다른 두 모터 교대 사용 워크플로우). 커뮤 설정 유효성은 모터 독립적인 **CA[17]==5 게이트가 전담**(유지), CA[7]은 evidence 기록+VALIDATE 정보성 emit만. expected_ca7 명시 시 opt-in 고정 게이트는 보존(다른모터 장착 감지용). 신규 테스트: CA[7]=272 모터 → 오경보 없이 GREEN·K_a ±2%·기록 유지 + 명시 pin은 여전히 RED. pytest **127 passed**·`--smoke-velpos` GREEN·스펙 §1/§5 G0 갱신.
- **브레이크어웨이 캡 UI 선택(2026-07-14)**: Tuning 페이지에 "브레이크어웨이 캡 (P2)" 드롭다운(**0.2·CL 기본/0.4·CL 고전류** — 16극 확정·커뮤 정상인데 기본 캡 무이탈인 이 유닛용) + 안전 안내(토크 ~2배·감독 필수·1200rpm 가드/조기종료 유지·0.4=캡 8.49A≥6A라 UM3 판별 자동 실행). `_velpos_overrides()`가 선택값을 `AutotuneVPParams(ramp_frac=…)`로 전달(워커 `**kw` 기존 경로), Phase 2 확인 다이얼로그에 선택 캡 표기. 커널 불변(RAMP_FRAC_ABS_MAX=0.4 사전게이트가 천장). 검증: `--smoke-velpos`에 3단언 추가(글루 레벨 ramp_frac=0.4→i_cap evidence 8.49 도달·UI 기본 0.2·선택 0.4) 전부 PASS, pytest **127 passed** 무회귀, `--smoke-autotune`/`--smoke` GREEN. 실기 재실행(0.4 선택)은 사용자 감독 별도.
- **방향 반전 안전보강 4건(fable-physics §3, 2026-07-14)**: 이 유닛=유효-역방향 커뮤(+TC→−피드백, CA[25]=1+재커뮤로 사용자 수리 예정). ① 방향 RED를 **램프 i_ba 래치 시점**으로 조기화(signed dpx/VX 판정, 진단펄스 통전 전 중단 — 실기는 19,571cnt 역회전 후 사망했었음; `breakaway.direction/±basis` evidence) ② unit-diag에 **ka_pos>0 단언**(실기 하드게이트가 음의 K_a −5.5e5로 PASS하던 구멍 — ka_dev는 크기 일관성만) ③ 3층 메시지를 "방향 반전(유효-역방향 커뮤): 수리=MO=0→CA[25]=1→재커뮤→SV"로 통일(묵시적 부호보정 금지 명문화) ④ design_vp_gains K_a>0 ValueError(음의 KP[2] 폭주 유입 차단). 교차검증: 반전 sim 램프 RED(dir=−1·dpx −15489·unit_diag 미생성)/FlipAfterRampSim diag서 K_a=−3.38e6 포착/design 거부/정방향 dir=+1 무영향. pytest **130 passed**(기존 반전 테스트 램프-시점으로 강화+신규 3)·`--smoke-velpos` GREEN·스펙 §14.2.
- **다음(실기, 사용자 감독)**: 새 유닛 Phase 2 재실행 — 예상: 램프가 i_ba(0.5~2.12A 사이) 실측→적응 펄스로 로터 실이동→위치기반 K_a 실측(FF[1]=1/K_a 확증=U-P1)·125× 종결. 무인 통전 금지.

### Single Axis Digital Inputs · Read-Only Snapshot v0.1 (2026-07-19)
- 설치 Gold UM Single Axis §8.9와 `IP`/`IL`/`IF` command reference를
  SHA-256 4개로 동결했다. explicit refresh는 `IL[1..6]`,
  `IF[1..6]`, final `IP`만 150ms/query·2s total·동일 session token으로
  읽는다. Digital Output, `IB` sticky clear, assignment, mapping/filter
  mutation, Enable/motion은 없음.
- pure fail-closed decoder와 Motion 6×5 read-only table, worker typed job,
  transport/operation catalog gate를 구현했다. invalid/reserved/session-change/
  timing 오류와 forged partial `CURRENT` snapshot은 전체 blank.
- 첫 Read Only field refresh는 transport allowlist 뒤 worker query-only
  job guard에서 막혔다. 허용-case test를 RED로 추가한 뒤
  `axis_digital_inputs_read` 하나만 observer job allowlist에 추가해 수정.
- 수정된 Python 3.14 새 창의 current-target observation:
  Input 1–6 모두 `ACTIVE · DRIVE LOGICAL`, `General purpose`,
  `ACTIVE_HIGH · non-sticky`, `0.000 ms`, acquisition `25.9 ms`.
  이는 raw pin voltage, wiring correctness, safety input 또는 EAS parity가 아님.
- 검증: focused `133 passed in 96.03s / exit 0`; 전체 stdout
  `1639 passed in 827.24s / 100% / stderr 0`. 전체 numeric exit watcher는
  빈 값이어서 그 숫자만 `UNVERIFIED`. 구현 HEAD `8c2a955a0d11c63c691b77f8eeeb21aaa5a2d269`.
- 다음 gate: EAS same-moment comparison, known inactive/active physical
  stimulus, polarity/filter/sticky timing. 그 전에는 safety interlock
  authority를 부여하지 않는다.

### Single Axis Digital Outputs · Read-Only Snapshot v0.1 (2026-07-19)
- installed Gold `OP`/`GO`/`OL` command pages와 local Gold Twitter
  Installation Guide를 SHA-256 4개로 동결했다. 매뉴얼 page 62–63 시각
  대조로 OUT1/2 5 V logic, OUT3/4 3.3 V logic을 고정했다.
- explicit refresh는 `OL[1..4]`, `GO[1..4]`, final `OP`만
  150 ms/query·2 s total·동일 session token으로 읽는다. assignment,
  `OB/OC/XO`, output toggle/actuation, Enable/motion은 없다.
- pure fail-closed decoder와 Motion 4×5 read-only table, transport/worker
  typed-job allowlist, operation catalog를 구현했다. `OL` range 0..9와
  Target Reached 10/11의 문서 충돌은 `OL_RANGE_CONFLICT`로 보존한다.
- current-target `ONLINE · READ ONLY` observation: Output 1–4 모두
  `INACTIVE · DRIVE LOGICAL ACTIVATION`, `General purpose`, `ACTIVE_HIGH`,
  `Function via OL[N]`, acquisition `18.1 ms`.
- 검증: pure `24 passed`, integration slice `113 passed in 46.12s`,
  직접 영향 범위 `276 passed in 53.27s / exit 0`, 전체 repository
  `1673 passed in 493.02s / exit 0`, source SHA-256 `4/4`;
  세 skin contrast ≥4.5:1, horizontal scroll 0.
- 구현 HEAD:
  `667c19eb8bd44d1a7d838772753e7fc6d709fb94`.
- physical pin voltage/current, external load/brake, EAS same-moment parity,
  output compare/STO indication 자극과 write/readback/rollback은
  `NEED-DATA / NO-GO`; 이 readback을 safety authority로 사용하지 않는다.

---

## 신규 목표 (2026-07-20): 모터-범용화 + EAS 자립 (북극성)

**사용자 북극성(/btw 2026-07-20):** 지금은 뭔가 틀리면 EAS로 재튜닝·재구동해서
원인을 찾는다. 최종 완료 시점에는 **EAS에 의존하지 않고 우리 프로그램만으로
재튜닝·진단·구동**이 되어야 한다 — "우리가 만든 게 곧 EAS처럼."

**두 갈래 요청:**
1. 조그를 3000rpm 시연 상수에서 **정격 3600rpm**까지. (주의: 3600 = 이 모터의
   전압한계 속도 = 토크여유 0. 정격까지 여는 것과 상시운전 마진은 구분.)
2. **특정 모터 하나에 그라운딩된 도구 → 어떤 모터를 연결해도** EAS처럼
   Quick Tuning · Expert Tuning · Motion/Single-Axis가 동작.

**현재 아키텍처 실태(2026-07-20 조사):** 라이브 경로는 이미 상당히 범용적.
- Motion·autotune는 드라이브에서 CA[18](counts/rev)·CA[19](극쌍)·VH[2](최대속도)·
  CA[28](모터타입)을 런타임에 읽음. 모터 상수 하드코딩 아님.
- Motor Settings 쓰기(_write_motor: CA[19]/CA[28]), Feedback(_on_feedback), Quick/Expert
  Tuning 페이지, Phase1(전류)·서명·Phase2(속도/위치) 오토튠, Apply 3단 검증 모두 존재.
- 모터-특정 잔재: (a) JOG_MAX_RPM_CEILING=3000 상수(single_axis_motion.py:83, 이 모터
  3600의 −17%), PEAK 세션캡도 3000 기준. (b) EAS 오라클 대조 상수(KP=0.0712/KI=812.9,
  R/L) — 검증 표시용, 게이트 아님. (c) POLE_PAIRS_FALLBACK=16(CA[19] 못 읽을 때).
- ⇒ 범용화의 실질 작업 = 속도/전류 상한을 드라이브-리드 리밋(VH[2]·PL[1]/CL[1]·CA[18])
  에서 **파생**시키고, 오라클 상수 의존을 **연결된 모터 기준으로 일반화**하는 것.

**열린 질문 (수용 기준과 함께 — 착수 전 사용자 확정 필요):**
- OQ1 "어떤 모터" 범위: 이 Gold Twitter 드라이브에 물리는 **임의 회전형 BLDC/PMSM**만인가,
  아니면 Gold **드라이브 계열 전반**(다른 Gold 모델)도? 선형모터/리졸버까지?
  수용기준: 지원 대상 목록을 명시하고, 미지원은 UI에서 명확히 NEED-DATA 락.
- OQ2 3600rpm 정격: 조그 상한을 **드라이브 VH[2]/CA[18]로 파생한 정격 rpm**으로
  자동 산정할까(모터 바뀌면 자동 추종), 아니면 3600 상수로 올릴까?
  수용기준: 모터 교체 시 상한이 자동으로 새 모터 정격을 따라가고, 전압한계=토크0
  구간은 경고로 표면화. 상시운전 권장은 정격의 N% 아래로 표기.
- OQ3 자립 진단 범위: "EAS 없이 진단"에 **커뮤테이션 확립(백래시 내성 커뮤 ID)**
  까지 포함인가? 원장상 EAS 위저드가 이 감속기에서 실패 + δ 전원마다 재추첨이라,
  진짜 자립하려면 앱이 커뮤 ID를 자체 구현해야 함(원장 2026-07-15 항목).
  수용기준: 전원 재인가 후 EAS 손 안 대고 서명 GREEN까지 앱 단독 도달.
- OQ4 검증 오라클: 모터가 임의라면 "EAS 게인과 대조"라는 그라운딩이 사라진다.
  범용 검증 기준을 무엇으로? (물리 타당범위 PM≥45°·ω_c 대역·루프게인 정합 등
  모터-불문 게이트로 전환) 수용기준: 모터별 EAS 정답 없이도 GREEN/YELLOW/RED 판정.

**북극성 2 (/btw 2026-07-20): UI도 EAS처럼 단순하게.** 현재 앱은 감사·증거·게이트
기능이 많이 쌓여 번잡하고 헷갈린다. 최종 UI는 EAS의 화면 구성/조작 흐름을 따라
**필요한 것만 앞에** 두고, 개발/감사용 잔재(Expert DOC MAP inspector류, 다중 evidence
패널 등)는 숨기거나 정리한다. 안전 게이트의 실질은 유지하되 표현은 EAS 수준으로 단순화.
- OQ5 UI 재구성 깊이: EAS 화면을 레퍼런스로 (a) 네비게이션/페이지 구성만 정리인가,
  (b) 개발용 inspector/evidence 페이지를 실제로 숨김/제거까지인가?
  수용기준: 초심자가 EAS 쓰던 감각으로 Quick Tuning→Motion까지 헤매지 않고 도달.

## 결정 확정 (2026-07-20, 사용자 4문항 + /btw)
- **OQ1 모터 범위 = 이 드라이브의 임의 회전형 BLDC/PMSM.** 선형/리졸버 등은 UI에서
  NEED-DATA 락. 검증 오라클(OQ4)은 EAS 게인 대조 대신 **모터-불문 물리 게이트**
  (PM≥45°·ω_c 대역·루프게인 정합·타당범위)로 전환.
- **OQ2 정격속도 = 모터별 값(하드코딩 3600 폐기).** 정격은 (a) 사용자가 UI에 입력하는
  모터 스펙 필드 + (b) 드라이브 VH[2]/CA[18]에서 파생, 두 소스로 확보. 조그/모션 상한·
  전류캡은 이 **연결된 모터의 정격**에서 파생 → 모터 교체 시 자동 추종. 전압한계=토크0
  구간은 경고로 표면화, 상시운전 권장은 정격의 N% 아래. (3600은 지금 이 모터의 정격 예시일 뿐.)
- **OQ3 커뮤 자립 = 포함.** 백래시 내성 커뮤테이션 ID를 앱에 자체 구현 → 전원 재인가 후
  EAS 손 안 대고 서명 GREEN까지 앱 단독 도달. 원장 2026-07-15(EAS 위저드 실패·δ 재추첨)
  재사용 자산(서명 게이트·UM3 드래그 오라클·HOLD-CONFIRM) 활용.
- **OQ5 UI = 네비/구성만 EAS식 정리(저위험).** 개발용 inspector/evidence 페이지는
  제거하지 않고 뒤로 물리거나 접기. 안전 게이트 실질 유지, 표현만 EAS 수준 단순화.

**북극성 종합:** 완료 시 = 어떤 회전형 모터를 물려도, 그 모터의 정격을 UI/드라이브로
받아, EAS 없이 우리 앱만으로 커뮤 확립→Quick/Expert 튜닝→Motion 구동까지, EAS식
단순 UI로. 검증은 모터-불문 물리 게이트로 GREEN/YELLOW/RED.

## 활성 계획 (2026-07-20, fable-planner 산출) — 7단계
P0 커뮤 명령 그라운딩(read-only) · P1 MotorProfile(신규) · P2 상한 프로필파생 ·
P3 오라클→물리게이트 · P4 커뮤 자립(실기핵심) · P5 UI EAS식 재배열 · P6 E2E 실기.
착수 = P0+P1 병렬. CP1: MotorProfile 계약 동결 후 전 단계가 그 위에 쌓임.
추가 발견 모터-특정 잔재: MAX_CURRENT_CAP_A=5.0, 서명대역 0.50~1.30A,
UM3_DRAG_I_A=6.0, ka_baseline 단일파일 교차오염, G3가 EAS FF[1] 의존.

## P2 물리 SPEC 동결 (fable-physics 2026-07-21)
전류캡: jog_cap_ceiling = f_I_def·CL[1] (舊 MAX_CURRENT_CAP_A=5.0 대체), 기본 f_I_run·CL[1]
(舊 3.0). f_I_def=0.25 · f_I_run=0.15 · f_I_max=0.5(하드,옵트인만) · k_hold=1.5 · MIN=0.10A.
전류는 드라이브 진폭 관습(√2 무개입). fail-closed=아래(전류↓). 프로필 무효 시 live CL[1]에 f_I_def.
속도상한: jog_ceiling_rpm = 1.0×effective_rated_rpm (분율 없음). 이중클램프: 요청검증(프로필,
초과=거부 침묵클램프금지) → 경고게이트 → preflight(live VH[2]) → per-tick 클램프 → 오버스피드.
라이브 VH[2]=런타임 최종권위. 프로필 무효 시 ceiling=JOG_MAX_RPM_DEFAULT=300(임의 3000/3600 폴백 금지).
전압경고: N_WARN=0.90 → 요청>0.90·rated 시 "토크여유0 접근" 확인 다이얼로그(차단 아님). 상시권장≤0.85.
타임박스: 로직 불변, v_cap=jog_ceiling_rpm·CA[18]/60 파생, 주석 상수→evidence[px_overflow_projection].
실기확인필요: 홀드전류3.25A(코드주석만)→i_ba_history로 대체, N=90 버스새그 성분 관례값, f_I_max×0.7 마진.

## 실기 그라운딩 확정 (2026-07-21, 읽기전용)
spikes/live_motor_profile.py로 COM3 Gold Twitter 실독(통전0). **P1/P2 실기 GREEN**:
MotorProfile이 실드라이브 값 정독 → effective_rated_rpm=3600·jog_ceiling=3600·warn=3240
파생 확인. 오라클 5/5 GREEN.
- **확정 사실: 현재 벤치 모터 = 극쌍 16** (사용자 확정 2026-07-21). 드라이브 CA[19]=16이
  맞는 값. 메모리의 "극쌍 21"은 과거 AngryYJH의 *다른 모터* — 이 모터에 적용 금지.
- **실기 TS 명령은 µs 반환**(TS='100'=100µs). from_sources는 초 단위 기대 →
  라이브 프로필 배선 시 ×1e-6 변환 필요(P3/오토튠이 TS 사용). 정격 파생엔 무관.

## P3 물리게이트 SPEC 동결 (fable-physics 2026-07-21) — 구현 대기(오프라인)
핵심: 기존 매직상수가 모두 모터-불문 공식임을 발견 — UM3_DRAG=0.4·CL/√2(=6.0 정확),
"토크효율70%"=1/√2=cos45° 커뮤문턱, GUARD=rated/3(=1200), verify=[0.10,0.25]·rated,
서명대역=[0.5,1.5]·i_ba_ref. 드라이브-규칙 상수(0.2010/1.2705/2.0=KI-TS결속)는 존치,
모터-특정(R/L/K_a/i_ba/FF1/EAS게인)만 프로필 파생. 신규 physics_gates.py(순수함수 GateVerdict),
서명 첫런 닭-달걀=방향+expect-slip(I=i_ba/√2, follow=δ≥45° RED), K_a드롭·서명대역 프로필별,
FF[1]/EAS대조→advisory 강등(게이트서 제거). 다중모터 시뮬 4종(A~D)+결함주입 RED+리터럴 트립와이어.
실기확인필요: κ_R경계·verify v1 300→360·GUARD클립.

## 서명 RED 진단 (2026-07-21 01:17, autotune_vp_result_1784564221124.json)
status=RED, reason="모터 폴트 MF=0x80". abort evidence: segment='idle',
steps_done=['A_mo MO=0','A_lim restore']. 즉 **MF=0x80이 MO=1 인에이블 직후(idle)에
발생** — 램프/브레이크어웨이 전. i_ba 미검출, 방향 -. abort 체인 정상(MO=0·리밋복원).
현재 드라이브 MF=0(Axis 스냅숏 확인, 폴트 클리어됨). 기어드 16극쌍.
가설(미검증): 커뮤 미확립 상태로 enable→speed-tracking 폴트. 내일 재커뮤 전략 필요
(출력축 프리무빙, P0 후보 A/B/C, 전류 상향). reason 문자열 인코딩 깨짐(cp949 함정) 별건.

## Admin PDF 판독 (2026-07-21) — MF·위저드 확정
- MF=0x80(128)="Speed tracking error"(Admin p.85 비트표). 오늘 서명 RED=커뮤 미확립 enable→추종실패 셧.
- EAS 위저드=UM=3 스테퍼 phasing(로터가 전기장 TC정토크로 따라감, 512cnt/극쌍). 후보 B-2와 일치.
  기어드 위저드 실패=±대칭이동 백래쉬 파손. P0 §7#6 프리미티브 해소, 앱은 후보 B로 재현 가능.

## P4 커뮤 자립 SPEC 동결 (fable-physics 2026-07-21) → docs/commutation-id-p4-spec.md
핵심: 180°플립 프리앰블이 MF=0x80 idle 해결(cos δ·cos(δ−180°) 동시 음 불가). 모델 교차검증
i_ba비4.566→|δ|102.7° vs 관측103°. 주경로 A(CA[7]재기록+플립)·폴백 B(CS)·최후 C(봉인).
신규 commutation_id.py 상태기계(S0~S6), CommutGearLashSim 시뮬 7시나리오, 내일 실기 런북 R0~R6.
실기확인 3건: CA[7] 부호 s·CS UM5생존·전원 δ재추첨. P3 구현 완료 후 P4 시뮬 구현 착수(같은 파일 충돌회피).

## P3 진행 (2026-07-21, Opus 자체구현)
위임 fable-driver 사일런트 데스(6h 무출력) → Opus 직접 구현. 1차 슬라이스 완료:
physics_gates.py(순수함수 12: p1_pm/wc_band/rho/r_relative/l_relative, sig_band/first_run,
ka_drop, derive_drag_current/guard_rpm/verify_speeds, p2_g1d, advisory_eas, combine) +
tests/test_physics_gates.py 25 passed(경계·상수재현 6.0/1200/360-900·다중모터A~D·결함주입·트립와이어).
SPEC 정정 1건: verify GUARD 캡 0.6→0.8(내부모순, 동결 900rpm 보존). **미착수(다음): autotune_current/
velpos 배선 = EAS오라클→physics_gates 소비(프로덕션 회귀 슬라이스), P4 시뮬 구현, P5 UI.**
