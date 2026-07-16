# 로컬 Elmo 자료 감사 기록

기준일: 2026-07-16
검사 범위:

- `<LOCAL_ELMO_ROOT>`
- `<LOCAL_GOLD_TWITTER_ROOT>`
- 이 저장소의 `vendor`, `lib_net`, `docs`

읽기·해시·문서 대조만 수행했다. 펌웨어 실행, 설치, flashing은 수행하지 않았다.

## 현재 장치에 우선하는 근거

현재 target과 가장 정확히 일치하는 artifact는
`lib_net/personality_model.xml`이다.

- identity: `Twitter 01.01.16.00 08Mar2020B01G Pal:90`
- SHA-256: `A1627CAAE98F2B47B6D091821AE271568E7D52E5D312301F2B41156208602A14`

바탕화면의 firmware package는 `01.02.18.00 B00`용이다. 더 최신이지만 현재
`01.01.16.00 B01G` 장치의 exact personality나 명령 계약을 대체하지 않는다.

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
