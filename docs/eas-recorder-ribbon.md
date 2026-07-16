# EAS III Recorder 상단 리본 기능 지도

기준일: 2026-07-16<br>
대상 화면: 사용자가 제공한 EAS III Recorder 리본 캡처<br>
구현 범위: `AngryYJH Control`의 단일 Gold Twitter 연결

이 문서는 EAS 화면을 그대로 복제했다는 선언이 아니다. 화면에서 직접 읽힌 라벨은
`OBSERVED`, 로컬 공식 Command Reference·Drive .NET 문서와 코드로 확인한 동작은
`DOCUMENTED`, 정확한 의미가 남은 항목은 `NEED-DATA`로 분리한다.

앱 상단에는 `File / Parameters / Tools / Views / Floating Tools`를 항상 표시한다. 이 메뉴는
EAS 원본 메뉴 동등성을 주장하지 않으며, `operation_catalog.py`의 공통 위험 분류를 사용해
페이지 이동과 앱 전용 Recorder JSON처럼 **로컬에서 끝나는 동작만 실행**한다. Quick Tuning은
식별·설계 안내 화면, Expert Tuning은 RAM trial·Verify·Restore·SV 화면으로 분리한다. 원본 EAS
파일 형식, 다축 모션, unrestricted Terminal, Fault/Status/Log처럼 실행 계약이 아직 없는 항목은
메뉴에 `NEED-DATA`로 보이되 비활성 상태를 유지한다. Recorder 문맥 리본은 Recorder 페이지에서만
보이고, 전역 `DRIVE STOP`과 상단 애플리케이션 메뉴는 모든 페이지에 고정 표시한다.

상단 메뉴를 여는 행위는 `LOCAL UI`다. 메뉴로 Tuning이나 Motion 페이지를 열어도 실행 버튼의
`DRIVE READ / RAM WRITE / ENERGIZES / MOTION / PERSIST-SV` 게이트는 바뀌거나 우회되지 않는다.

## 사용자가 먼저 알아야 할 구분

- **Recorder Stop**: 기록 버퍼 취득만 중단한다. 모터를 정지하지 않는다. Vendor
  `StopRecorder()`가 예외 없이 반환한 것만으로 성공 처리하지 않고, 같은 recorder에서
  `ROff` 또는 `REnd`를 되읽은 뒤에만 소유권을 해제한다. 이미 `UploadRecordingData()`가
  실행 중이면 vendor 호출 자체는 선점할 수 없지만, 반환된 host data를 폐기하고 늦은
  `COMPLETED`/data를 게시하지 않으며 UI 종결 상태를 `CANCELLED`로 유지한다.
- **DRIVE STOP**: 앱의 소프트웨어 안전 탈출 경로 `ST → MO=0`을 실행하고 되읽는다.
  독립 STO나 E-stop은 아니다. 같은 worker에서 이미 실행 중인 vendor 호출을 선점할 수 없으므로
  Personality discovery와 Upload는 fresh `MO=0/SO=0/VX=0`에서만 허용한다.
- **Immediate Capture**: 선택한 신호를 유한 길이로 한 번 기록한다. v1의 유일한 live trigger다.
- **Workspace Open/Save**: 이 앱의 로컬 JSON 설정 파일이다. EAS 파일 호환을 주장하지 않는다.

## 리본 항목별 상태

| EAS 화면 항목 | 쉬운 설명 | 현재 구현 | 근거/잠금 이유 |
|---|---|---|---|
| Target `Drive01` | 기록 명령을 받을 드라이브 | 단일 연결 대상으로 고정 | 앱 구조상 worker 하나가 target 하나를 소유 |
| Filter / Lock Target | 장치 목록 필터와 대상 고정 | 단일-drive 고정만 구현 | EAS 필터 규칙은 `NEED-DATA` |
| Open / Save / Save As | Recorder 문서·설정 파일 | `STAND-IN`: 앱 전용 versioned JSON | EAS 원본 파일 형식은 미확인; EAS 호환을 주장하지 않음 |
| Resolution | 원하는 샘플 간격 | 구현 | `TS`를 읽어 정수 `TimeResolution`으로 해석하고 실제 간격을 별도 표시 |
| Record Time | 유한 기록 시간 | 구현 | 실제 간격×샘플 수로 계산 |
| Buffer Size | 기록 가능한 버퍼 | 16K 총 샘플 사용량으로 구현 | EAS 화면의 `8 s` host/rollover buffer와 동일한 필드인지는 미확인 |
| Single / Rollover | 1회 기록 / 순환 기록 | Single만 구현 | Rollover의 정확한 .NET 계약이 `NEED-DATA` |
| Signals… | Personality 신호 선택 | 구현 | 연결된 드라이브의 정확한 신호 이름 사용, 최대 16채널 |
| Trigger… | Begin/analog/digital/window 등 | 비활성 placeholder | 공식 trigger 종류는 문서화됐지만 UI·복구 계약이 아직 없음 |
| Single / Normal / Auto | trigger/acquisition 정책 | 비활성 placeholder | EAS UI 의미와 .NET `TriggerMode`의 일대일 대응 미확인 |
| Interval… | 주기적 반복 기록 | 비활성 placeholder | scheduler, overlap, cancel 정책 미확인 |
| Start | 설정된 trigger로 arm/start | 비활성 placeholder | Immediate와의 정확한 UI 차이가 `INFERRED` |
| Immediate | 즉시 한 번 기록 | 구현 | `.NET TriggerSetupType.Immediate` |
| Upload | 완료된 drive buffer를 host로 가져오기 | 구현 | `UploadRecordingData()`, physical doubles |
| 작은 Stop | Recorder만 취소 | 구현 | `StopRecorder()`; motion 명령 없음 |
| Load / Save / Settings Preset | acquisition preset | `STAND-IN`: 앱 전용 JSON Save As | EAS preset schema 호환은 주장하지 않음 |
| Multi Drive Recording | 여러 drive 동시 기록 | 비활성 placeholder | clock sync, partial failure, 시간축 정렬이 `NEED-DATA` |
| Manage Drives | multi-drive 대상 관리 | 비활성/미구현 | target identity, clock sync, partial failure 계약이 `NEED-DATA` |
| 우측 trash 아이콘 | 선택/설정/recording 삭제로 보임 | 비활성/미구현 | 캡처만으로 삭제 범위와 복구 의미를 확정할 수 없음 |
| 우측 큰 STOP | 전역 software motion stop으로 보임 | `DRIVE STOP`으로 명시 구현 | EAS 내부 명령 범위는 `UNVERIFIED`; 앱은 `ST → MO=0`만 주장 |
| Recording / View Design 탭 | 기록 설정 / 표시 설계 전환 | Recording v1 + local read-only View Design 구현 | EAS 원본 layout schema는 `NEED-DATA` |
| View Design | 완료 capture의 두 chart 신호 배치·표시 | `STAND-IN`: exact signal명, `index×dt`, 2-lane local JSON v3 | EAS 파일 호환·단위 추론 없음 |
| Manual Zoom / Apply to All | 확대 범위를 여러 chart에 적용 | `STAND-IN`: 공통 X(time) 범위만 두 chart에 적용; Y는 독립 | EAS의 X/Y/XY·대상·undo/persistency 규칙은 `NEED-DATA` |
| FFT Zero Scale | FFT chart의 Y scale을 0에서 시작 | `STAND-IN`: full-capture one-sided peak FFT, Y 하한 0 | 일반 Zero Scale 의미는 NetHelp `DOCUMENTED`; FFT window/scaling/unit/DC/Nyquist는 `NEED-DATA` |
| Exponential axis formatting | 작은 축 범위의 숫자를 지수 표기로 표시 | `STAND-IN`: 로컬 axis span `< 0.001`일 때 tick label만 지수 표기 | EAS의 span 계산 축·반올림·경계 규칙은 `NEED-DATA` |
| Signal Statistics | 선택 signal의 endpoint/구간 기술 통계 | full+A:B field, endpoint/delta, RMS/Tolerance % + local mouse drag/snap + provenance-bound Statistics CSV | 수식·nearest 원본 sample 의미는 `STATIC-IL VERIFIED`; 로컬 안정화 계산은 극단값 bit-identical rounding 미주장; EAS glyph/shortcut/persistency/file parity는 `NEED-DATA` |

## v1 상태 흐름

`IDLE → CONFIGURING → RECORDING/WAITING_FOR_TRIGGER → READY_TO_UPLOAD → UPLOADING → COMPLETED`

회복 상태는 `READY_TO_UPLOAD`(Upload 재시도 또는 Recorder Stop),
`STALE_CONNECTION_UNKNOWN`, `CANCEL_FAILED_UNKNOWN`, `START_OWNERSHIP_UNKNOWN`,
`RECOVERY_REQUIRED_UNKNOWN`이다. `START_OWNERSHIP_UNKNOWN`은 vendor `StartRecording()` 호출을
통과한 뒤 예외가 발생해 실제 arm 여부를 증명할 수 없다는 뜻이다. 이 상태에서는 설정과 다른
제어를 계속 잠그고 Recorder Stop만 허용한다. Vendor의 `ROff`는 정상 cancel과 error 원인을
충분히 구분하지 못하므로 `OFF_CAUSE_UNKNOWN`으로 표시한다.

연결 해제 중 Recorder Stop의 `ROff`/`REnd` 확인을 얻지 못하면 v2 복구 latch를
`.omc/state/recorder_unknown.json`에 원자적으로 남긴다. 기록은 COM 포트와 hashed drive
identity의 조합으로 구분된다. 다음 세션은 현재 drive identity가 같은 record에만 Recorder
Stop 복구를 적용하며, 같은 COM에 연결된 다른 drive가 기존 record를 지울 수 없다. Identity를
읽을 수 없거나 legacy record의 identity가 불명확하면 일치를 증명할 수 없으므로 fail-closed로
남는다. 일치하는 live session에서 Stop 후 `ROff`/`REnd`까지 확인해야 latch를 지운다. 파일에는
원시 drive 식별자나 오류 전문 대신 hashed identity와 예외 형식만 저장한다.

## 16K 버퍼와 시간 계산

드라이브 recorder의 총 저장량은 16,384 samples다. 채널 수가 `N`이면 채널당 최대 길이는
`floor(16384/N)`이다. 앱은 요청한 `resolution_us`를 drive `TS`의 정수 배수로 해석하고,
다음 값을 화면과 결과에 분리한다.

- requested resolution
- actual resolution
- requested record time
- actual record time
- samples per signal
- total buffer samples

용량을 넘으면 자동 축소하지 않고 시작 전에 거부한다.

Drive .NET 1.0.0.8 공식 `DriveDotNetRecording/RecordingOperator.cs` 예제는
`SamplingTime=TS`(µs), `TimeResolution=4`로 설정하고 실제 간격을
`TimeResolution × TS`로 계산한다. 앱도 이 의미를 사용하며 Upload 직전에 Configure 객체의
`SamplingTime`, `TimeResolution`, `RecordingLength`를 각각 설정값과 정확히 대조한다.
어느 값이 달라졌거나 finite·positive 조건을 만족하지 않으면 데이터를 Upload 완료로
판정하지 않고 `READY_TO_UPLOAD`에서 재시도 또는 Recorder Stop만 허용한다.

## 데이터와 단위

Upload 결과는 Drive .NET이 반환한 physical doubles다. 모든 채널이 요청 길이와 정확히
같고 모든 sample과 `dt`가 finite일 때만 `COMPLETED`가 된다. CSV에는 `time_s`와 Personality의
정확한 신호 이름을 사용한다. 신호 이름만 보고 단위를 발명하지 않으며, unit metadata가
별도로 검증되기 전까지 단위는 `personality-owned`로 기록한다. CSV 옆에는 capture UUID,
시작 시도·검증 완료 UTC timestamp, target/firmware/PAL/boot, 요청·실제 timing, sample 수,
CSV SHA-256을 담은 `.meta.json` sidecar를 생성한다. CSV와 sidecar는 각각 temp-write/replace되지만
두 파일 전체가 하나의 원자적 filesystem transaction인 것은 아니므로 export 완료 메시지는 둘 다
성공한 뒤에만 표시한다. 같은 capture manifest에는
`main.py`·`elmo_link.py`·`recorder_control.py` source SHA-256, Drive .NET DLL path/SHA-256,
Personality XML path/SHA-256·signal-catalog SHA-256·source, 그리고 원시 `SN[4]`를 노출하지 않는
hashed drive identity가 포함된다.

캐시 Personality는 XML `<version>`의 firmware 부분이 비어 있지 않은 live `VR`을 정규화한
값과 정확히 일치하고 `Pal:` 값도 live `VP`와 일치할 때만 사용한다. 일치하지 않거나 증명할
수 없으면 현재 연결에서 Personality를 다시 upload한다. Vendor communication 객체에 이미
들어 있던 signal catalog는 신호 source로 사용할 수 있지만 XML version 대조가 없으므로
firmware match를 주장하지 않는다. 선택된 Personality source와 match 결과는 sidecar에 남긴다.

캡처가 시작되면 신호, Resolution, Record Time, Open/Save/Preset을 동결한다. 연결이 바뀌면
이전 Personality 신호 권한을 폐기하고 새 target에서 Signals를 다시 발견하기 전까지
Immediate를 잠근다. Workspace 신호가 새 Personality에 일부라도 없으면 부분 적용하지 않고
사용자가 현재 신호를 다시 선택하게 한다.

## View Design — Local Time + FFT + A:B Signal Statistics

`View Design`의 로컬 Time/FFT/Statistics는 Drive Recording을 다시 실행하거나 드라이브 설정을 쓰는 기능이
아니다. worker/`ElmoLink` 참조가 없는 read-only renderer이며, `COMPLETED` + `VALIDATED`
manifest와 동일 worker generation/capture ID completion token이 정확히 일치하는 capture만 받는다. UI에서 `validate_capture()`를 다시 실행하므로
`dt`, sample 수, finite 값, exact signal name 중 하나라도 불일치하면 차트와 CSV 권한을 모두
열지 않는다.

- Chart 1/2는 기본적으로 각각 한 신호를 표시한다.
- 각 chart의 `Show` 토글로 숨김/표시를 바꿀 수 있어 저장된 hidden lane을 UI에서 복구할 수 있다.
- x축은 `index × actual dt`; y축은 숫자 범위만 표시하고 물리 단위를 발명하지 않는다.
- chart·summary·CSV는 검증 시 만든 하나의 immutable evidence snapshot을 공유한다.
- 총 16K sample 상한과 lane당 1채널 제한 안에서 full immutable waveform을 렌더하고 auto
  y-range도 full evidence에서 계산한다. raw CSV는 별도 분석·보관 증거다.
- Manual Time Zoom은 원본 sample을 재구성하거나 감축하지 않고 capture 안의 공통 X(time)
  viewport만 두 chart에 적용한다. 최소 2개의 실제 sample을 포함해야 하며 Full Time으로 되돌릴 수 있다.
- FFT는 검증된 full immutable capture 전체를 사용한다. 수동 시간창은 FFT 표시 중 무시하지만
  값은 보존하므로 시간 파형으로 돌아오면 같은 viewport를 복구한다.
- 로컬 FFT 계약은 one-sided peak amplitude, 직사각 창, detrend 없음, zero padding 없음,
  DC 포함이다. Y축 하한은 0으로 고정하며 단위는 `personality-owned amplitude; not inferred`다.
- 로컬 axis span이 `0.001` 미만이면 tick label만 지수 표기로 바꾼다. 정확히 `0.001`이면
  일반 표기를 유지하며 원본 또는 FFT 숫자는 변경하지 않는다.
- Signal Statistics는 full immutable capture 전체 또는 exact integer sample A:B의 inclusive
  구간에서 Min/Max/Average/RMS AC/RMS DC/Tolerance/Tolerance %를 계산한다. A/B endpoint
  Signal Values, exact sample time, signed `ΔX/ΔY=C2-C1`도 함께 표시한다. 통계는 `DERIVED`, read-only이고 Manual
  Zoom/FFT/lane 선택과 독립이며 raw CSV를 대체하지 않는다. 파생값 overflow는 통계 표만 거부하고
  유효 capture/CSV 권한은 유지한다. Tolerance %만 표현 불가능하면 해당 cell을 `N/A`로 잠근다.
  Analyze Statistics의 `startIndex < endIndex` gate와 같이 N=1이면 잠근다. EAS live cursor panel은
  동일 sample N=1도 계산하므로 현재 결합 UI는 그 경로보다 엄격하다.
- A/B는 `N=B-A+1`인 정수 sample index authority다. Time chart의 선을 drag하면 현재 visible
  viewport 안의 nearest 원본 sample로 snap하고 동률은 낮은 index를 택한다. A<B를 유지하며 release
  때 inclusive 통계를 한 번 계산한다. FFT에서는 선택을 보존하되 편집을 잠근다. 시간 문자열을
  index로 역변환하지 않으며 range를 바꾸면 stale 통계와 endpoint rows를 즉시 지운다.
- `Export Statistics CSV…`는 표시 중인 exact result와 동일한 immutable source view일 때만 열린다.
  한 signal당 한 row로 capture binding, source SHA-256, full/A:B scope, endpoint와 통계, signal order,
  CURRENT 또는 HISTORICAL_OFFLINE authority를 넣는다. 단일 UTF-8 local-only 파일을 temp+fsync+replace로
  게시하고 최종 bytes를 다시 확인한다. Save dialog 중 capture/result/authority가 바뀌면 export를
  취소한다. raw capture CSV를 대체하거나 EAS Save As 호환을 주장하지 않는다.
- chart별 Y 범위는 독립이다. 서로 다른 Personality 신호의 단위를 추정하지 않으므로 Y 숫자 범위를
  chart 사이에 복사하지 않는다.
- 새 capture 시작 시 이전 plot authority를 즉시 폐기한다.
- 연결이 바뀌면 기존 chart는 남길 수 있지만 `HISTORICAL / OFFLINE`으로 표시한다.
- 로컬 layout은 `angryyjh-recorder-view-layout/v3`이며 shared `x_range_s`와 `plot_mode`를 저장한다.
  v1은 Full Time + time mode로, v2는 저장된 시간창 + time mode로 이관한다. v2의
  `x_range_s` 또는 v3의 `x_range_s`/`plot_mode`가 없거나 future schema이면 거부한다. EAS 파일
  호환을 주장하지 않는다.

EAS 3.0.0.26 Release Notes p.4에서 `Manual Zoom - Apply to All`, `FFT Zero Scale`,
`exponential axis formatting for ranges below 0.001`이라는 기능 이름을 `OBSERVED`했다. 이 세
항목에 관해 Release Notes가 직접 뒷받침하는 것은 이름뿐이다. 사용자 조작 영상의 Chart #1
메뉴에서도 `Manual Zoom`은 관측되지만
Apply-to-All 실행 화면은 없다. 따라서 X/Y/XY 범위, 적용 chart 수, clamp/undo, capture
교체·재시작 뒤 수명은 `NEED-DATA`이고 현재 구현은 `Apply X-range to both charts (local)`로
명시한다. 설치된 EAS III 3.0.0.26 NetHelp는 일반 Zero Scale을 Y scale이 숫자 0에서 시작하는
표시로 직접 정의한다. 이를 Release Notes의 FFT Zero Scale에 연결하는 것은 강한 `INFERRED`다.
FFT 입력 구간, window/detrend/zero-padding, amplitude/power/PSD scaling, 단위와 DC/Nyquist
처리는 `NEED-DATA`다. 현재 FFT/Y축 0/지수 표기는 위에 적은
로컬 `STAND-IN` 계약이며, Normal persistency는 아직 구현하지 않았다.

같은 설치 NetHelp의 `EASIII Infrastructure.htm`(SHA-256
`52355DA5481ABEA257C43AB9E728B510D99F5BB369D803819DDAF0AE8D2526C6`)은 entire signal 통계와
Min/Max/Average/RMS AC/RMS DC/Tolerance field와 결과가 보기 전용이라는 의미를 직접 정의한다.
그러나 prose의 Root Mean Square와 literal MathML/수식 이미지의 `sqrt(sum)/N`은 서로 모순된다.
설치 ViewModel DLL의 `AnalyzeStatisticsViewModel.SetStatisticsByRange()`와 별도 Action DLL의 IL은
모두 sum-of-squares를 N으로 나눈 뒤 `Math.Sqrt`를 호출하므로 표준 RMS 의미가
`STATIC-IL VERIFIED`다. 로컬 안정화 계산은 극단값 bit-identical rounding까지 주장하지 않는다.
Tolerance %의 runtime 식은
`average == 0 ? 0 : abs(Tolerance/Average/2)*100`으로 확인했고 local A:B range에 적용했다.
로컬 mouse drag/snap과 통계 CSV는 위의 제한된 계약으로 구현했다. EAS Marker/Cursor의 정확한
glyph/UI shortcut/persistency/file parity와 FFT-bin range는 이번 범위가 아니다.

설치 View.dll의 `FindNearestIndexOfCursor()`/`SetNearestValues()`와 Action DLL의 `Calculate2D()`를
대조해 명시적 cursor가 nearest 원본 sample의 x/y를 쓰고 Signal Values의 delta가 signed C2-C1인
것을 `STATIC-IL VERIFIED`했다. 로컬 v1은 그 sample authority를 직접 보이는 정수 A/B spinbox로
노출한다.

## 근거

- `docs/man-g-cr_GoldLine_CommandReference.pdf`, MAN-G-CR 1.406, recorder p.252–265
- `docs/recording-api.md`
- `elmo_link.py`: Personality, `record_start`, `record_status`, `record_upload`, `record_stop`
- `recorder_control.py`: timing/buffer validation, workspace schema, CSV export
- `<LOCAL_ELMO_ROOT>/Drive .NET Library 1.0.0.8 Release Notes.pdf`
- `<LOCAL_ELMO_ROOT>/Drive .NET Library 1.0.0.8 Code Examples.zip`
  - SHA-256 `0E12B2B332D35E26DD5B81797E442D568BA966FE752930B849C19E09F7379222`
  - member `Code Examples/DriveDotNetRecording/RecordingOperator.cs`
- `<LOCAL_ELMO_ROOT>/EAS 3.0.0.26 Release Notes.pdf`
- `C:/Program Files/Elmo Motion Control/Elmo Application Studio III/NetHelp/Content/`
  `EAS_II_SimplIQ_Gold_UM/Supporting Tools.htm`
  - SHA-256 `300B980C11BF37A5AE20803AA3038C178A2E6CD0785959791124EFA6739AAEC4`
  - Recording Properties / Chart Editor: 일반 Zero Scale은 Y scale을 0에서 시작
- `C:/Program Files/Elmo Motion Control/Elmo Application Studio III/NetHelp/Content/`
  `EAS_II_SimplIQ_Gold_UM/EASIII Infrastructure.htm`
  - SHA-256 `52355DA5481ABEA257C43AB9E728B510D99F5BB369D803819DDAF0AE8D2526C6`
  - Analyze Statistics: entire signal 및 여섯 통계 field, view-only 의미
- `C:/Program Files/Elmo Motion Control/Elmo Application Studio III/`
  `ElmoMotionControl.Recorder.ViewModel.dll`
  - SHA-256 `8F59E3DD9CC4D6667322050806CB0D75649795234311C3662D4E039ACD890B46`
  - `SetStatisticsByRange()` token `0x06000029`: divide by inclusive N, then `Math.Sqrt`
- 같은 설치 폴더의 `ElmoMotionControl.Recorder.Action.dll`
  - SHA-256 `C0296B1E59DD9BEEEF568D033E9DC1741752DBEE9CD905F2AF425D3A93B0347E`
  - `CalculateValuesAndStatisticsAction.Calculate2D()` token `0x06000156`: 독립 동일 순서
- 같은 설치 폴더의 `ElmoMotionControl.Recorder.Model.dll`
  - SHA-256 `5F66B295F1A3AC318594A91FC4AF06223E6B09DD169EA419D5C382745A9D2739`
  - `SignalStatistics.get_TolerancePercent()` token `0x060003E4`: zero mean→0, 그 외 절대 half-range/mean %

## 검증 명령

```text
python -m pytest tests/test_recorder_control.py tests/test_recorder_view.py \
  tests/test_main_recorder_view.py tests/test_elmo_recorder_lifecycle.py
python main.py --smoke-recorder
```

두 검증은 하드웨어 I/O를 수행하지 않는다.
