# 로컬 Elmo 자료 감사 기록

기준일: 2026-07-18
검사 범위:

- `<LOCAL_ELMO_ROOT>`
- `<LOCAL_GOLD_TWITTER_ROOT>`
- 이 저장소의 `vendor`, `lib_net`, `docs`

읽기·해시·문서 대조만 수행했다. 펌웨어 실행, 설치, flashing은 수행하지 않았다.

## 현재 장치에 우선하는 근거

현재 target의 런타임 명령/신호 계약에 우선하는 artifact는
`lib_net/personality_model.xml`이다.

- identity: `Twitter 01.01.16.00 08Mar2020B01G Pal:90`
- SHA-256: `A1627CAAE98F2B47B6D091821AE271568E7D52E5D312301F2B41156208602A14`

2026-07-18 재감사에서 `Version 1.1.16.0 B01 for customers.zip`이 추가로
확인됐다. 내부 member 이름의 `NGDrive 01.01.16.00 08Mar2020B01G.gabs`는
현재 personality의 firmware 문자열과 일치한다. 그러나 package 이름의 `B01`과
firmware member의 `B01G` 의미 차이는 문서적으로 아직 `NEED-DATA`이며, 이 package가
현재 personality나 실제 drive readback보다 우선하지 않는다.

## 2026-07-18 증분 인벤토리

읽기 전용 재귀 스캔 결과:

- 파일 59개, 총 5,691,086,215 bytes
- PDF 30, ZIP 15, RAR 5, MP4 3, ABS 2, GABS/XML/PPTX/JPG 각 1
- 59개 모두 SHA-256 산출
- ZIP/RAR 20개는 member 목록만 읽었으며 추출·실행하지 않음
- 이전 감사 기준 이후 mtime 파일 38개, 총 122,140,318 bytes

mtime은 로컬 갱신 시점만 나타내며 upstream 생성 시점이나 새 버전임을 증명하지 않는다.

### 현재 firmware와 파일명 수준으로 일치한 package

`Version 1.1.16.0 B01 for customers.zip`

- 크기: 1,756,165 bytes
- SHA-256:
  `6A79E0C2956EA643916FFF5526450BEB66D47BAE6C8DB1C7E92A993CF8B4C74F`
- member:
  - `FoEFW 01.01.16.00 08Mar2020B01G.abs`
  - `FoEFW FoEPal 01.01.16.00 08Mar2020B01EG_001.abs`
  - `FoEPal 01.01.16.00 08Mar2020B01EG_001.pbin`
  - `NGDrive 01.01.16.00 08Mar2020B01G.gabs`
  - `Elmo ECAT 00010420 V11.xml`

판정은 **파일명/identity 후보 일치**까지다. 내부 firmware 의미 검증, 장치 호환성
검증, flashing 검증은 수행하지 않았다.

### 별도 firmware 세대

다음 package도 확인했지만 현재 target에 혼용하면 안 된다.

- `Version 1_1_14_5 B02.zip`:
  `E8B6BB7D993118A998B85F0C640A15BD829635327BB45B2FDB1F17E33C3965B8`
- `Version-1_1_15_0-B00.zip`:
  `5C51BB63A66CF93AF70BDA474BA97AD46438BA03CB075723AA268EF80A61A058`
- `Version 1_2_17_0 B10 Custmers.rar`:
  `23676F937C70A0DD2AC67C8C6EC1AF7F78BA27677DC1BDDAA0D35AD03C753946`
- `Version 1_2_17_2 B00 Customer.rar`:
  `3A58E92161C0A7828109396E683103B9777ABAA40B3EF1D31964DFD7079398B9`
- `Version 1_2_18_0 B00 For Customers.rar`:
  `3719FDBD2111C81C5473736FAB150B3F906C6F0D10DEED4E2C3F20AC7F701247`

### EAS와 Drive .NET 참고 자료

- `EAS 3.0.0.26 Release Notes.pdf`:
  `FC3CCD1A5FBE47944EEF8E2FCEE10433E253B8026759281DB3284BB310B12904`
- `EAS II 2.9 Presentation.pptx`:
  `2075A6C989A78F27210D76602A73E143AF5DF74CBDD8CC449BA05B3D6BE9697C`
- EAS II Exercises 1/2/3/6/7/10과 2.7/2.7.2 release/installation 자료
- `Drive .NET Library 1.0.0.8 Code Examples.zip`:
  `0E12B2B332D35E26DD5B81797E442D568BA966FE752930B849C19E09F7379222`
  (464 entries, 정적 검토 전용; EXE/PDB 실행 안 함)
- `Drive .NET Library 1.0.0.8.zip`:
  `3C80FFF771595DE4DF7E64C894AB2AD74B2E5C876AAA804A3551BFAA8B016F8F`
  (내부 DLL은 저장소 사본과 byte-identical)

Quick Tuning, Single Axis, Feedback, Recorder의 EAS 동작 대조에는 위 EAS 자료를
우선하고, Drive .NET 예제는 호출 패턴의 정적 근거로만 사용한다.

### Gold Drum 후속 호환성 근거

- `MAN-G-DRUMIG-EC-DTYPE.pdf`:
  `5DB3CEDADAB0ACEAD3800BBEFDC9403AA5479CC862C716D4356F594F6B6F8954`
- `MAN-G-DRUMIG-EC-RJ45.pdf`:
  `00A62C48EB8173766207C29110498AC129F0C30021173A0A23FB3F9F8C58AEA0`

이 자료는 후속 Gold Twitter↔Gold Drum 호환성 매트릭스의 근거이며 현재 Twitter
검증을 Drum 검증으로 대체하지 않는다.

### 범위 제한

- PDF/PPTX의 본문 의미론 검토는 이번 증분 인벤토리에 포함하지 않았다.
- 압축 내부 member의 개별 SHA-256은 산출하지 않았다.
- 4.39 GB `Feedback Setting.mp4`, 약 573 MB Cubemars 영상, 약 554 MB 조작
  영상은 파일 SHA-256만 산출했고 재생·프레임 분석하지 않았다.

## 중요 발견

1. 외부 원본/RAR의 `NGDrive ...B00G.gabs`는 2,975,917 bytes,
   SHA-256 `A6A212B8B7E8367A517F18F50DFD9F80881C4122C3599A6C880437A7A93F9C44`다.
2. 저장소 vendor 사본은 2,975,919 bytes,
   SHA-256 `5507915C0DDAD9375EA2DFF095EBDF137A1E06D860CC73C0767C30A038ECE5FA`다.
3. vendor 사본에는 CR(`0x0D`) 2 bytes가 추가됐다. Firmware blob은 semantic
   equivalence가 아니라 byte identity가 기준이므로 **vendor 사본을 flashing artifact로 쓰면 안 된다**.
4. Drive .NET 1.0.0.8 DLL/zip과 주요 PDF는 외부 폴더와 저장소 사본이 동일하다.
5. code examples의 Personality는 Trombone 01.01.09.10/PAL48이므로 현재 Twitter에 부적합하다.

## 현재 firmware에 필요한 방어

Release history와 current personality를 함께 보면 다음 방어를 유지해야 한다.

- 매 finite move마다 `FS=0`을 쓰고 BG 직전 다시 읽는다.
- `SF[1]`, `SF[2]`를 매 move 재발행하고 읽는다.
- JP와 PA를 섞지 않는다.
- target firmware는 01.01.16.10 이전이므로 SF power-up 적용 문제 가능성을 배제하지 않는다.
- exact B01과 B01G 사이 delta는 `NEED-DATA`다.

## Gold Twitter 브레이크/출력 주의

Gold Twitter hardware manual은 OUT1/2를 5 V logic, OUT3/4를 3.3 V logic으로 정의한다.
Generic Command Reference의 `OL[1] supplies brake current` 문장을 Twitter의 직접 브레이크
코일 구동 능력으로 해석하면 안 된다. 실제 브레이크에는 외부 driver/relay와 wiring,
polarity, delay 검증이 필요하다. 따라서 Axis Summary의 `BP[1]/BP[2]`, `SC[13]`은 현재
raw read-only 값으로만 표시한다.

## 사용 금지/보류

- 사용자 명시 승인과 별도 recovery 절차 없이 firmware flashing 금지
- 01.02.18 ESI XML을 현재 personality로 사용 금지
- vendor의 byte-altered `.gabs`를 firmware source로 사용 금지
- 현재 personality에 없는 `SC[16]` 구현 금지
