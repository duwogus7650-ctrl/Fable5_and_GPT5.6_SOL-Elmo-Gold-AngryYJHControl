<!-- scope_progress: 100 -->
<!-- offline_progress: 100 -->
<!-- field_progress: 10 -->
<!-- progress_basis: Planning indicators, not safety scores. Field progress records bounded read-only observations only; it does not represent motion, protection, STO, or EAS parity validation. -->

# Gold Twitter · Quick + Single Axis + Expert v2

상태: **POSITION / VELOCITY REFERENCE READ v0.1 · CURRENT DRIVE READ ONLY**

업데이트: **2026-07-19 KST**

## 이번 진행 결과

- `Position / Velocity References · Read-Only Snapshot v0.1` 구현 완료.
- 정확히 18개 query만 사용:
  `MO/SO/MF/SR` pre/post,
  `UM`, `PA[1]`, `PR[1]`, `JV`, `SP[1]`, `AC[1]`, `DC`, `SD`, `PX`, `VX`.
- assignment, `BG`, `MO=1`, 모드 변경, enable, energization, motion은 실행하지 않음.
- PA/PR/JV는 **configured / queued readback**이며 active command 또는 motion proof가 아님.
- transport는 위 exact query만 허용하고 assignment, 다른 index, lookalike를 계속 차단.
- UI에는 편집 control이 없고 `Refresh ... READ ONLY` 버튼 하나만 존재.
- 실제 화면 검증에서 숨겨졌던 `VX` 9번째 행을 발견해 표 높이를 수정하고 재검증 완료.

## 현재 검증

- `OBSERVED` pure decoder/reader: **56 passed**.
- `OBSERVED` transport + pure: **144 passed**.
- `OBSERVED` authority/UI/catalog/transport 직접 영향 범위: **244 passed**.
- `OBSERVED` closeout 영향 범위(모니터 포함): **270 passed in 104.51s**.
- `OBSERVED` 설치 Gold command source SHA-256: **13 / 13 일치**.
- `OBSERVED` 전체 repository 회귀: **1868 passed in 735.79s (12:15)**.
- `git diff --check`: **exit 0**.

## COM3 read-only 관찰

- 상태: `ONLINE · READ ONLY`, `DISABLED REPORTED`, `UM=5 Position`.
- `PA[1]=0 cnt`, `PR[1]=0 cnt`, `JV=0 cnt/s`.
- `SP[1]=4,444,444 cnt/s`.
- `AC[1]=DC=SD=1,000,000 cnt/s²`; `AC/DC WITHIN SD`.
- `PX=-2,038,379,934 cnt`, `VX=0.000 cnt/s`.
- acquisition: **35.6 ms**.
- `PX=0` 또는 다른 쓰기는 실행하지 않음.

이 값은 현재 Gold Twitter drive readback이다. EAS same-moment parity,
physical motion capability, safe travel envelope, stopping distance,
independent STO/E-stop, Gold family compatibility를 증명하지 않는다.

## 현재 slice closeout

- 구현, 문서, runtime readback, source identity, 영향 범위 및 전체 회귀 완료.
- private branch commit/push와 Draft PR #2 갱신 준비 완료.
- 다음 기능은 command surface가 아니라 Recorder/Single Axis의 남은
  read-only 또는 documented-map 범위에서 별도 계약으로 시작한다.

## 계속 잠긴 기능

- PA/PR/JV assignment와 `BG` 실행.
- standalone `MO=1`, Drive Mode 변경, Current command `TC=`.
- endless Jog, Run Held, Sine/Homing/Stepper.
- unrestricted Terminal.
- 실제 Expert Bode/Time Verify, Apply/SV.

이 기능들은 단순 UI 구현 문제가 아니라 단위·방향·travel/speed/acceleration,
current/thermal/torque envelope, watchdog, 독립 abort/STO, readback,
`ST -> MO=0` closeout이 필요한 `NEED-DATA / NO-GO` 범위다.
