# Expert User Units · Documented Formula Preview v0.1

## 목적과 판정

이 기능은 EAS III Expert Tuning의 `Drive User Units → DS-402 Format`에
표시된 **위치 스케일 식 하나**를 명시적 수동 입력으로 계산하는 순수 로컬
검사기다.

- 판정: `PARTIAL / SCREENING`
- authority: `DOCUMENTED_FORMULA_PREVIEW`
- 입력 근거: 사용자가 직접 입력한 `FC[1], FC[2], FC[5], FC[6], FC[7], FC[8]`
- 금지: drive readback, 자동 채움, FC/OF command, Apply, Revert, SV,
  Motion/Recorder/Status Monitor 단위 전파
- 고정 경계:
  `EXPLICIT MANUAL INPUT · DOCUMENTED FORMULA PREVIEW · PARTIAL SCREENING ·
  NOT CURRENT DRIVE CONFIG · NO FC/OF WRITE · NO APPLY/SV · NO DRIVE I/O`

이 결과는 현재 드라이브 구성, EAS 계산 완료, 설정 적합성 또는 motion safety
판정이 아니다.

## 원문에서 직접 확인한 식

설치된 NetHelp의 식 이미지는 다음 비율을 표시한다.

\[
\frac{\text{Position User Units}}{\text{Encoder Counts}}
=
\frac{FC[2]\times FC[6]\times FC[7]}
{FC[1]\times FC[5]\times FC[8]}
\]

구현은 부동소수점으로 식을 재배열하지 않고 Python `Fraction`으로 정확한
유리수를 만든다. 화면에는 exact fraction과 최대 15 유효숫자의 bounded decimal을
함께 표시한다.

NetHelp 예제:

- `FC[1]=10000`
- `FC[2]=1`
- `FC[5]=1`
- `FC[6]=1`
- `FC[7]=1000`
- `FC[8]=10`

결과는 정확히 `1/100 = 0.01 user unit/count`이며, sample `100 counts`는
`1 user unit`이다.

## DOCUMENTED GROUPING MISMATCH · PURPOSE NEED-DATA

MAN-G-CR은 `FC[1..8]`에 다음 제한을 별도로 적는다.

- `FC[1] × FC[6] × FC[8] < 2^63`
- `FC[2] × FC[5] × FC[7] < 2^63`

이 두 묶음은 위 NetHelp 식의 분자·분모 묶음과 같지 않다. 공개 자료만으로는
이 제한이 내부 역변환/중간 계산을 위한 것인지, 문서 수정이 필요한 것인지
판별할 수 없다. 따라서 구현은:

1. NetHelp 식을 그대로 계산하고,
2. MAN-G-CR의 두 제한을 문자 그대로 별도 guard로 적용하며,
3. 어느 한쪽으로 인덱스를 정규화하거나 제한을 “식 overflow 증명”이라고
   재해석하지 않고,
4. mismatch와 `PURPOSE NEED-DATA`를 화면과 결과 객체에 항상 남긴다.

각 FC 입력은 MAN-G-CR 범위대로 strict integer `1..2^31-1`만 허용한다.
`bool`, float, 문자열을 순수 모델 API에 넘기면 거부한다. 두 documented product는
정확히 `2^63`인 경계부터 거부한다.

## UI 상태 계약

| 상태 | 의미 |
|---|---|
| `PARTIAL / SCREENING · waiting` | 모든 FC 필드는 blank이며 자동 채움이 없음 |
| `DOCUMENTED LOCAL PREVIEW` | 현재 명시 입력으로 exact formula preview를 계산함 |
| `STALE` | 계산 뒤 입력이 바뀌어 이전 결과는 historical only |
| `INVALID` | 새 입력이 잘못됨; 이전 완전한 preview/result는 보존 |

unit label은 표시 문자열일 뿐 drive 단위 metadata가 아니다. sample counts는
선택 입력이며 로컬 표시 안전을 위해 signed 64-bit 범위로 제한한다. 이 제한은
drive command range가 아니다.

기존 `CA[18]`, Axis Summary의 `FC[*]`, telemetry, P1/P2 candidate,
installed gain readback, Page Status snapshot을 읽거나 바꾸지 않는다.
Motion/Recorder/Status Monitor의 canonical 단위는 계속 `cnt`, `cnt/s`다.

## 구현과 검증

- 순수 모델: `expert_user_units.py`
- Expert 다섯 번째 단계: `5 · USER UNITS`
- operation id: `tuning.expert.user_units.preview`
- operation risk/status: `LOCAL_UI / PARTIAL`
- gate/menu: 없음 / top-menu 비노출
- 집중 테스트:
  - exact golden fraction, reciprocal, sample conversion
  - FC1↔FC2 및 FC5↔FC6 식 mutation 음성 대조
  - strict type/range와 두 documented product의 `==2^63` 경계
  - frozen/deterministic result와 source hash 고정
  - file/process/network/worker/link/dispatch poison I/O
  - blank·자동 채움 금지, stale/invalid historical retention
  - P1/P2/evidence/Page Status/installed/Verify/Apply/Save 권한 불변
  - qdd/amber/angrybirds 1366×820에서 수평 스크롤과 단계 버튼 잘림 없음

## 근거 identity

| 근거 | SHA-256 | 직접 관찰 |
|---|---|---|
| 설치 NetHelp `Drive Setup and Motion Activities.htm` | `BD824C372BBBE7F0928F0F805F51EDA2C5CD73150AB3C20F9DE6279E9006E8EE` | §8.2.5.1.2, FC 의미와 예제 |
| NetHelp 식 이미지 `_56.jpg` | `772B95FB672E43F54573AE498F137450810E601EB76636790275BC2B2E935CD9` | 731×47 px, 식의 FC 인덱스 |
| NetHelp DS-402 화면 `_63.png` | `8DC946881AD2BC70E7776A03153A4EE92C35C11456603F3EA2356F5B823838AD` | 1005×658 px, EAS page 구조 |
| `docs/man-g-cr_GoldLine_CommandReference.pdf` | `89280DB57DBBE6877945CC8C4720C959B8295E68806DECBFB9F43892994C2A80` | FC 범위와 두 product guard |

실행 중인 EAS에서 drive disconnected 상태로 직접 관찰한 것은
`Display User Units` page다. `Axis Configuration → Using Drive User Units`가
unchecked여서 `Drive User Units` page는 숨겨져 있었고, DS-402 page 구조와 식은
위 hash의 NetHelp HTML/image에서 확인했다. Connect, Apply, Revert, Save, Upload,
Download는 실행하지 않았다.

## 명시적 비범위

- Simplified Format
- `FC[9..12]` velocity/acceleration factor
- `OF[14]` polarity
- Display User Units 자동 선택·rounding·motor/load 계산
- 현재 drive FC readback/compare
- command preview, Apply/Revert/Apply All, SV, import/export
- EAS page icon/Enter/Summary/file parity
- safety limit, PTP, tuning gain 또는 recorder data의 단위 변환
