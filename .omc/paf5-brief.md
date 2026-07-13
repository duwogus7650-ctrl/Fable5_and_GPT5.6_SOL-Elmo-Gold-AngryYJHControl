# PAF5 Brief — Fable5-Elmo-Control-Program

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
