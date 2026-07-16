# Recorder View Design — Time + FFT + A:B Signal Statistics

기준일: 2026-07-16
범위: AngryYJH Control의 단일-drive Immediate finite capture를 위한 로컬 읽기 전용 표시

## 화면에서 보이는 두 탭

- `Recording · Immediate v1`: Personality 신호 선택, 실제 샘플 간격/길이 계산, 기록,
  Upload Buffer → PC, Recorder Stop, raw CSV export를 담당한다.
- `View Design`의 로컬 Time/FFT/Statistics: 검증 완료된 capture의 exact signal name과 숫자
  sample만 Chart 1/2의 시간 파형 또는 로컬 FFT로 표시한다. 전체 capture 또는 정수 sample index
  `A < B`의 양끝 포함 구간에 대해 endpoint Signal Values와 통계를 읽기 전용으로 계산한다.
  공통 시간창을 두 차트에 적용할 수 있지만 드라이브 명령, 설정 쓰기, Recorder 재시작 기능은 없다.

`DRIVE STOP`은 전역 software motion stop이고 `Recorder Stop`은 Recorder buffer lifecycle만
중단한다. 두 버튼은 의미와 위치를 계속 분리한다. 어느 쪽도 독립 STO/E-stop은 아니다.

## 표시 권한 게이트

다음 조건이 모두 맞아야 View 탭이 열린다.

1. worker가 capture를 `COMPLETED`로 끝냈다.
2. manifest의 `completion`이 `VALIDATED`다.
3. manifest와 `ResolvedRecorderRequest`의 exact signal order와 sample 수가 일치한다.
4. `recorder_control.validate_capture()`가 `dt`, 실제 duration, 배열 길이, numeric/finite sample을
   다시 통과시킨다.
5. capture ID, UI generation, drive identity가 빈 값이 아니며 현재 권한과 결속된다. production
   worker는 UUID와 opaque hashed drive identity를 생성하지만 View validator 자체는 형식까지
   인증하지 않는다.
6. worker manifest와 data completion token의 capture ID/generation이 정확히 일치한다.

실패하면 새 차트를 만들지 않고 raw CSV 권한도 열지 않는다. 새 capture를 누르는 순간 이전
View authority와 manifest generation을 먼저 폐기한 후 worker job을 큐에 넣는다. 연결 변경 뒤
남겨 둔 과거 차트는 `HISTORICAL / OFFLINE`이며 현재 target의 증거가 아니다.

## 데이터 의미

- x축: `x[i] = i × actual_dt`
- y축: Drive .NET Upload가 반환한 physical double의 immutable evidence snapshot
- 이름: Personality의 exact signal name
- 단위: `personality-owned; not inferred`
- 차트·요약·CSV: 검증 시 한 번 만든 `CaptureEvidence`의 같은 dt/channel tuple/manifest를 사용
- 표시: 드라이브의 총 16K sample 상한과 lane당 1채널 제한을 이용해 v1은 full immutable
  waveform을 그린다. auto y-range도 같은 full evidence에서 계산한다. raw CSV는 별도 분석·보관
  증거이며 화면 plot만으로 현장 안전 판정을 확정하지 않는다.
- Manual Time Zoom은 immutable waveform을 자르거나 감축하지 않고 렌더러의 공통 X(time)
  viewport만 바꾼다. 범위는 capture 안의 실제 sample을 최소 2개 포함해야 한다. `Reset Full Time`은
  전체 capture 시간축으로 복귀한다.
- 로컬 FFT는 수동 시간창이 아니라 검증된 full immutable capture 전체를 입력으로 사용한다.
  시간창은 FFT 표시 중 무시하지만 그대로 보존해 시간 파형으로 돌아왔을 때 복원한다.
- FFT는 `STAND-IN` one-sided peak amplitude다. 직사각 창, detrend 없음, zero padding 없음,
  DC 포함을 고정한다. `|rfft|/N`에서 DC와 짝수 길이의 Nyquist bin은 두 배로 만들지 않고,
  나머지 양의 주파수 bin은 두 배로 만든다. 단위는 계속
  `personality-owned amplitude; not inferred`이며 EAS와 같은 scaling이라고 주장하지 않는다.
- FFT chart의 Y축 하한은 항상 0이다. 모든 값이 0인 capture도 임의 진폭을 만들지 않는다.
- 로컬 축의 표시 span이 `0.001` 미만이면 tick label만 지수 표기로 바꾼다. span이 정확히
  `0.001`인 경우는 일반 표기이며, 이 규칙은 sample이나 FFT 값 자체를 변경하지 않는다.
- 두 chart의 Y 범위는 서로 독립이다. Personality 신호마다 단위가 다를 수 있으므로
  Apply-to-All이 Y 숫자 범위를 복사한다고 추정하지 않는다.
- `Signal Statistics`는 각 exact signal의 전체 immutable sample 또는 sample-indexed A:B 구간에 대해
  `Min`, `Max`, `Average`, `RMS AC`, `RMS DC`, `Tolerance`, `Tolerance %`를 `DERIVED`로 계산한다.
  `RMS AC = sqrt(mean((x-average)^2))`, `RMS DC = sqrt(mean(x^2))`,
  `Tolerance = Max-Min`, `Tolerance % = average == 0 ? 0 :
  abs(Tolerance/Average/2)*100`이다. 이 의미는 설치 EAS 3.0.0.26 runtime IL로
  `STATIC-IL VERIFIED`했다.
  로컬 구현은 exact-sum fallback, magnitude-scaled RMS와 translated AC domain으로 finite
  극단값·큰 DC offset의 작은 spread를 처리하므로 EAS의 단순 double loop와 의미는 같지만 극단값의
  bit-identical rounding까지 주장하지 않는다. Min/RMS/Tolerance 자체를 finite로 표현할 수 없으면
  통계 표만 거부하고 capture/CSV 권한은 유지한다. 다른 필드는 finite지만 Tolerance %만 표현
  불가능하면 그 cell을 `N/A`로 잠근다. Analyze Statistics 경로 IL의 `startIndex < endIndex`
  gate에 맞춰 sample이 하나뿐인 capture에서는 이 결합 통계 UI를 잠근다. 별도 EAS live cursor
  panel은 두 cursor가 같은 sample을 가리키는 N=1도 계산하므로 두 경로를 동일하다고 주장하지 않는다.
- A/B 선택의 authority는 반올림된 시간 문자열이 아니라 full capture의 정수 index다.
  `N = B-A+1`, 표시 시간은 exact `x_s[index]`, Signal Values는 `y[A]`, `y[B]`, signed
  `ΔX=x[B]-x[A]`, `ΔY=y[B]-y[A]`다. A/B 수직선은
  Time chart에만 표시하며 FFT로 바꾸면 선택은 보존하되 편집을 잠근다. Manual Zoom, lane,
  visibility와 FFT bin은 통계 입력이 아니다. 범위를 바꾸는 즉시 이전 파생 표를 지워 stale 결과가
  새 index와 함께 보이지 않게 한다.
- 통계는 Manual Time Zoom, chart lane/visibility, FFT 표시와 무관하며 raw CSV를 대체하지 않는다.
  새 capture가 시작되면 이전 통계를 지우고, 연결 변경 후 retained capture에서는 계산을 허용해도
  결과와 화면을 `HISTORICAL / OFFLINE`으로 유지한다.

서로 다른 단위를 임의로 합성하지 않도록 기본값은 chart당 신호 하나다. y축에는 검증되지 않은
`A`, `V`, `rpm` 같은 단위를 붙이지 않는다. 각 chart의 `Show`를 직접 켜고 끌 수 있으므로
숨김 상태가 포함된 로컬 레이아웃도 UI에서 복구할 수 있다.

## 로컬 레이아웃

`angryyjh-recorder-view-layout/v3` JSON은 정확히 두 lane의 channel(각 lane 최대 1개), visible,
독립 y-range(auto 또는 finite min/max), 공통 `x_range_s`(`full` 또는 finite `[min,max]`),
`plot_mode`(`time` 또는 `fft`)를 저장한다. v1 파일은 `x_range_s=full`, `plot_mode=time`으로,
v2 파일은 저장된 `x_range_s`를 유지하고 `plot_mode=time`으로 이관한다. v2의 `x_range_s`와
v3의 `x_range_s`/`plot_mode`는 필수다. unknown/future schema, v1 파일의 임의 `x_range_s`, 현재
capture에 없는 channel, NaN/Inf, 음수 시간, `min >= max`, capture 밖 시간창은 거부한다. 파일은
atomic temp-write 후 replace하며 `local-only; not EAS-compatible` 선언을 반드시 포함한다.

## EAS 근거와 비범위

- 사용자 제공 조작 영상의 keyframe에서 `Recording / View Design`, Chart #1/#2와 Chart #1
  우클릭 메뉴의 `Manual Zoom`을 `OBSERVED`했다. 같은 프레임에는 `Apply to All` 실행 결과가 없다.
- 로컬 `EAS 3.0.0.26 Release Notes.pdf` p.4(SHA-256
  `FC3CCD1A5FBE47944EEF8E2FCEE10433E253B8026759281DB3284BB310B12904`)에서
  `Manual Zoom - Apply to All`, `FFT Zero Scale`, `exponential axis formatting for ranges below
  0.001`이라는 기능 이름을 `OBSERVED`했다. 이 세 항목에 관해 Release Notes가 직접 뒷받침하는
  것은 이름뿐이며 입력, 수치 처리, 축 범위 또는 저장 수명은 확정되지 않는다.
- 설치된 EAS III 3.0.0.26 NetHelp의 `EAS_II_SimplIQ_Gold_UM/Supporting Tools.htm`
  (SHA-256 `300B980C11BF37A5AE20803AA3038C178A2E6CD0785959791124EFA6739AAEC4`),
  Recording Properties/Chart Editor는 일반 `Zero Scale`을 `Y scale`이 숫자 0에서 시작하는
  표시로 직접 정의한다. Release Notes의 `FFT Zero Scale`에 이 일반 의미를 연결하는 것은
  근거가 강한 `INFERRED`이며, FFT 수치 처리 규약을 정의하지는 않는다.
- 같은 NetHelp의 `EASIII Infrastructure.htm`(SHA-256
  `52355DA5481ABEA257C43AB9E728B510D99F5BB369D803819DDAF0AE8D2526C6`)은 Analyze Statistics의
  entire-signal 범위와 Min/Max/Average/RMS AC/RMS DC/Tolerance 필드, 결과가 보기 전용이라는
  의미를 직접 정의한다. 그러나 prose의 `Root Mean Square`와 달리 literal MathML 및 원본 수식
  이미지 `Supporting Tools_68.png`/`_69.png`는 `sqrt(sum)/N`으로 N을 근호 밖에 표시한다.
  설치 `ElmoMotionControl.Recorder.ViewModel.dll`(3.0.0.26, SHA-256
  `8F59E3DD9CC4D6667322050806CB0D75649795234311C3662D4E039ACD890B46`)의
  `AnalyzeStatisticsViewModel.SetStatisticsByRange()` token `0x06000029` IL은 AC/DC sum-of-squares를
  inclusive N으로 나눈 뒤 `System.Math.Sqrt`를 호출한다. 별도
  `ElmoMotionControl.Recorder.Action.dll`(SHA-256
  `C0296B1E59DD9BEEEF568D033E9DC1741752DBEE9CD905F2AF425D3A93B0347E`)의
`CalculateValuesAndStatisticsAction.Calculate2D()` token `0x06000156`도 같은 순서다.
따라서 원본 수식 이미지는 vendor documentation defect이고 runtime 의미는 표준 RMS로
`STATIC-IL VERIFIED`다.
- 설치 `ElmoMotionControl.Recorder.View.dll`(SHA-256
  `37B98EFEA692DDB1EC481C4CE5C902EB22C674A9F78031C22DC3141B80A6EA`)의
  `CustomCursorModifier.FindNearestIndexOfCursor()` token `0x0600037D`와
  `SetNearestValues()` token `0x0600037F`는 cursor를 nearest 원본 sample에 결속한다. Action DLL의
  `Calculate2D()`는 endpoint `x[i], y[i]`와 signed `C2-C1` delta를 Signal Values에 전달하고,
  통계용 index는 min/max로 정렬해 양끝 포함한다. 이 endpoint/delta 의미도 `STATIC-IL VERIFIED`다.
- EAS 원본 layout/preset schema, `.mat` 세부 metadata, Rollover, Normal/Auto/Interval,
  advanced trigger, Multi Drive Recording은 현재 `NEED-DATA`다.

따라서 현재 기능 중 `Local Manual Time Zoom`, `Apply X-range to both charts`,
`Local FFT Magnitude / Zero-inclusive Y`, `Local exponential axis labels`는 `STAND-IN`이고,
`Full Capture Signal Statistics`와 inclusive A:B 통계는 `DOCUMENTED` field와
`STATIC-IL VERIFIED` RMS/Tolerance % 의미를 안정화된 로컬 수치 계산으로 구현한다.
EAS의 Apply-to-All이 X/Y/XY 중 무엇을 어느 chart까지 어떤 clamp·undo·persistency 규칙으로
복사하는지는 `NEED-DATA`다. EAS 일반 Zero Scale의 Y축 0 시작 의미는 `DOCUMENTED`지만,
FFT의 입력 구간, window/detrend/zero-padding, amplitude/power/PSD scaling, 단위와 DC/Nyquist
처리는 `NEED-DATA`다. 위 로컬 FFT 계약은
이 미확정 의미를 대신하는 명시적 구현 계약일 뿐 EAS 호환이라고 부르지 않는다. Advanced
trigger와 Normal persistency는 별도 vendor API·저장 수명·실패 복구 계약이 확정된 뒤 다룬다.
`ElmoMotionControl.Recorder.Model.dll`(SHA-256
`5F66B295F1A3AC318594A91FC4AF06223E6B09DD169EA419D5C382745A9D2739`)의
`SignalStatistics.get_TolerancePercent()` token `0x060003E4` IL은
`average == 0 ? 0 : abs(Tolerance/Average/2)*100`으로 확인했다. 로컬 UI는 exact integer
sample-indexed A/B와 endpoint table로 이 식을 적용한다. Time chart의 A/B 선은 visible viewport
안의 nearest 원본 sample로 mouse drag/snap하며 동률은 낮은 index를 선택한다. A<B를 유지하고
release 때 inclusive 통계를 한 번 계산한다. 통계 CSV는 `angryyjh-recorder-statistics-csv/v1`
local-only 단일 파일이며 capture binding, exact source-view SHA-256, scope/range, ordered signal rows,
CURRENT/HISTORICAL_OFFLINE authority를 포함한다. 전체 payload를 먼저 만들고 같은 디렉터리의
temporary file을 flush+fsync한 뒤 `os.replace`하고 최종 target bytes를 다시 확인한다. Save dialog의
nested event loop 뒤에는 exact view/result/evidence object, generation과 current/historical 상태를
다시 확인하며 하나라도 바뀌면 파일을 만들지 않는다. EAS Marker/Cursor의 정확한 glyph·shortcut·
persistency/file parity와 FFT-bin range는 계속 `NEED-DATA`다.

## 오프라인 검증

```text
python -m pytest tests/test_recorder_view.py tests/test_main_recorder_view.py \
  tests/test_recorder_control.py tests/test_elmo_recorder_lifecycle.py
python main.py --smoke-recorder
```

위 검증은 일부 fake `ElmoLink` 객체를 만들지만 COM 포트를 열거나 드라이브 I/O를 수행하지 않는다.
