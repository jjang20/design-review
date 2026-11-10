---
name: setup
description: 시험 키트 설정 — 대시보드를 게시해 주소를 저장하고, 이 세션에 데이터베이스 도구와 덱 커넥터(Canva · Google Slides)가 있는지 확인해 승인 방법을 안내한다. 사용자가 "설정해 줘", "설치 마무리", "setup"이라고 하거나 시험 키트 안내 문단을 붙여 넣었을 때 사용한다.
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/kit/drs_kit.py *)
---

# 설정 (Template DRS 시험 키트 0.0.2)

이 스킬은 **빈 플러그인**을 시험하기 위한 준비를 한다. 판정 기능은 아직 없다. 시험자는 개발자가 아니라고 가정하고, 아래 말투(쉬운 한국어, 한 번에 한 가지)로 안내한다. 용어를 쓸 때는 바로 풀어 쓴다.

도우미 스크립트: `python3 ${CLAUDE_PLUGIN_ROOT}/kit/drs_kit.py` (아래 `kit`). 단계 이름 · 진행 표시 · 실패 문구 · 이어하기 상태는 모두 이 스크립트가 정한다. 문구를 지어내지 않는다.
`${CLAUDE_PLUGIN_ROOT}`가 비어 있으면(플러그인을 막 설치해 아직 불러오지 않은 세션) 설치된 플러그인 폴더의 실제 경로를 `claude plugin list --json`의 설치 경로로 찾아 같은 방식으로 쓴다.

## 0. 시작 전 안내 (맨 처음 한 번)

1. `kit estimate`의 출력을 그대로 보여 준다(예상 시간 · 클릭 횟수 · 이어하기 안내). 안내 문단에서 이미 같은 내용을 보여 줬다면 생략한다.
2. `kit start`를 실행한다(환경은 스크립트가 `CLAUDE_CODE_ENTRYPOINT`로 알아낸다. 모르면 `unknown`).
3. 출력의 `notice`가 비어 있지 않으면 그대로 한 줄로 보여 준다. 이어하기(`resumed`가 true)는 **환경을 알고, 같은 환경이고, 아직 끝나지 않은 점검일 때만** 일어난다. 환경을 알 수 없거나(`unknown`) 환경이 바뀌었거나 이전 점검이 이미 끝났거나 상태 파일이 깨졌으면 스크립트가 처음부터 새로 시작하고 `notice`가 그 이유를 말한다. 이어하기일 때만 이미 통과한 단계를 다시 하지 않는다.

각 단계를 시작할 때 `kit status`의 `next_progress`(예: `3/5 · 대시보드 게시 · 주소 저장`)를 한 줄로 보여 준다. 단계가 끝나면 `kit mark <단계> pass`(또는 `fail --code <코드>`)로 기록하고, 그 출력 한 줄을 그대로 보여 준다. 실패하면 **그 한 줄("다음에 할 일: …")만** 보여 주고 멈춘다. 원인 추측이나 긴 설명을 덧붙이지 않는다.

## 1. 단계 1/5 · 플러그인 설치 확인 (`plugin`)

`${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json`을 읽어 `name`이 `design-review`이고 `version`이 `0.0.2`인지 본다. 맞으면 `pass`, 아니면 `fail --code plugin-not-found`.

## 2. 단계 2/5 · 빈 엔진 응답 (`engine`)

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/kit/drs_kit.py engine-ping
```

출력 JSON의 `ok`가 true면 `pass`, 아니면 `fail --code engine-error`.

## 3. 단계 3/5 · 대시보드 게시 · 주소 저장 (`dashboard`)

1. `kit dashboard-check`를 실행한다. 출력이 `REUSE <주소>`면 이 플러그인이 싣고 온 바로 그 판이 이미 게시돼 있다는 뜻이다(저장된 해시가 같다). 그 주소로 `Artifact` 도구 `read`를 해 읽히면 `pass`. 읽히지 않으면 2번으로 간다.
2. 출력이 `PUBLISH`면(저장된 주소가 없거나, 옛 판이거나, 다른 판이거나, 파일이 깨졌을 때) 저장된 주소를 쓰지 않는다. `${CLAUDE_PLUGIN_ROOT}/dashboard/index.html`을 `Artifact` 도구로 새로 게시한다. `capabilities: {"db": {}}`, 아이콘 `queue`. 돌려받은 주소를 `kit dashboard-save <주소>`로 저장한다(주소와 판의 해시가 함께 저장된다. 손으로 파일을 쓰지 않는다).
3. 게시되면 `pass`. `Artifact` 도구가 이 세션에 없으면 `fail --code no-artifact-tool`, 게시가 거절되거나 오류면 `fail --code publish-failed`.

대시보드는 본인 계정에 **비공개**로 올라간다. 시험자에게 이 한 줄을 알려 준다: "대시보드는 본인에게만 보이는 비공개 페이지로 올라갔습니다."

## 4. 단계 4/5 · 데이터베이스 도구 (`db`)

이 세션에서 `ArtifactData` 도구를 쓸 수 있는지 본다. 도구 목록에 이름만 있고 아직 불러오지 않았다면 `ToolSearch`로 `select:ArtifactData`를 먼저 부른다. 설정 단계에서는 **있는지만** 확인한다(한 바퀴 시험은 `check`에서 한다).

- 있으면 이 단계는 `pass`로 기록하지 말고 그대로 둔다(`check`가 끝까지 확인한다). 시험자에게는 "데이터베이스 도구가 있습니다"라고만 알린다.
- 없으면 `fail --code no-db-tool`.

## 5. 단계 5/5 · 덱 커넥터 (`connectors`)

덱을 읽는 커넥터 두 가지(Canva, Google Slides)가 이 세션에 연결돼 있는지 도구 목록에서 본다. 이름에 `Canva` 또는 `Google Slides`(또는 `Google_Slides`)가 들어간 도구가 있으면 연결된 것이다. **슬라이드 내용을 읽는 호출은 하지 않는다.** 도구가 있다는 사실만 본다. "로그인이 필요하다"고 표시된 커넥터는 연결되지 않은 것이다.

- 하나라도 연결돼 있으면 `kit mark connectors pass --connectors canva,google_slides`(연결된 것만).
- 하나도 없으면 아래 안내를 하고 `fail --code none-connected`로 기록한다. 로그인과 승인은 시험자만 할 수 있어서 대신 할 수 없다.

커넥터 승인 안내(그대로 말한다):

> 이 단계는 직접 눌러야 해서 제가 대신할 수 없습니다. Claude 설정의 **커넥터**에서 **Canva** 또는 **Google Slides** 중 하나 이상을 골라 **연결**을 누르고, 나오는 승인 화면에서 **허용**을 눌러 주세요. 끝나면 저에게 "점검해 줘"라고 말씀해 주세요.

## 6. 마무리

- 통과한 단계 수를 한 줄로 말한다(예: "준비 3/5 끝").
- 커넥터를 이미 승인했다면 바로 `check` 스킬 절차로 이어 간다. 아니라면 위 승인 안내 뒤에 시험자가 "점검해 줘"라고 말하기를 기다린다.
- 시험자가 "점검해 줘"라고 하면 `check` 스킬을 쓴다. 스킬 목록에 아직 `check`가 보이지 않으면(플러그인을 막 설치해 불러오지 않은 세션) `${CLAUDE_PLUGIN_ROOT}/skills/check/SKILL.md`를 읽고 그 절차를 그대로 따른다.

## 지키는 것

- 이름 · 이메일 · 계정 주소 · 슬라이드 내용은 읽지도, 기록하지도, 말하지도 않는다.
- 시험자가 입력해야 하는 것은 승인 클릭뿐이다. 로그인 · 비밀번호 · 승인 화면은 대신 하지 않는다.
- 판정은 하지 않는다. 이 버전에는 판정 기능이 없다.
