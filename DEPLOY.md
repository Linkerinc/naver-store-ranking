# 웹서비스(사이트) 버전 배포 가이드 — 운영사용

대리점이 설치 없이 **사이트 주소로 접속해서 쓰는 버전**을 배포하는 방법입니다.
호스팅은 Render.com **무료 플랜** 기준 (카드 등록 불필요). 약 15분 걸립니다.

무료 플랜 특성 (일단 이렇게 시작, 나중에 유료 전환 가능):
- 15분간 접속이 없으면 잠듦 → 다음 첫 접속자는 약 1분 대기 후 열림
- 서버가 재시작되면 등록 정보·키워드·리포트가 초기화됨
  (대리점 키워드는 각자 브라우저에 자동 백업되므로, 같은 브라우저에서
   재등록하면 키워드는 자동 복원됩니다. 전용 링크는 새로 발급)

## 1. 준비물

- 이 깃허브 저장소 (server_app.py, requirements.txt, render.yaml 포함 상태)
- 네이버 검색 API 키 1개 (운영사 것 — 대리점은 키가 필요 없습니다)
  - 발급: https://developers.naver.com/apps → 애플리케이션 등록 → "검색" 선택

## 2. Render 배포 (한 번만)

1. https://render.com 접속 → **Sign in with GitHub** 로 가입/로그인
2. 대시보드에서 **New + → Blueprint** 클릭
3. `naver-store-ranking` 저장소 선택 → Connect
4. 환경변수 입력 화면에서:
   - `NAVER_CLIENT_ID` : 네이버 API Client ID
   - `NAVER_CLIENT_SECRET` : 네이버 API Client Secret
5. **Apply** 클릭 → 몇 분 뒤 배포 완료
6. 서비스 주소 확인: `https://naver-store-ranking.onrender.com` 형태
   (Settings에서 이름을 바꾸면 주소도 바뀜. 자체 도메인 연결도 가능)

## 3. 대리점 안내 (이것만 전달하면 끝)

> 아래 주소로 접속해서 스마트스토어 주소를 입력하고 등록하세요.
> 등록하면 나오는 **전용 페이지 주소를 꼭 즐겨찾기** 해두고,
> 그 페이지에서 키워드를 등록하면 됩니다.
> 페이지의 "지금 수집하기" 버튼으로 원할 때 수집하면 됩니다.
>
> https://naver-store-ranking.onrender.com

## 4. 관리자 페이지

`https://서비스주소/admin/관리자키` 로 접속하면 등록된 전체 스토어 목록,
각 스토어의 전용 링크·키워드 수·수집 횟수를 볼 수 있습니다.

- 관리자키 확인: Render 대시보드 → 서비스 → Environment → `ADMIN_KEY` 값
- 대리점이 전용 주소를 잃어버렸을 때 여기서 찾아서 다시 알려주면 됩니다

## 5. 운영 참고

- **API 한도**: 무료 하루 25,000회. 스토어당 키워드 30개 제한 기준으로
  대리점 50곳 이상도 여유 있습니다 (수집 1회 = 스토어당 최대 300회)
- **수동 수집 제한**: 같은 스토어는 10분에 1회만 (한도 보호)
- **데이터 초기화 시**: 대리점에게 "다시 등록해 주세요" 안내 (키워드는 자동 복원)
- **코드 수정 시**: 깃허브 저장소에 파일을 올리면 Render가 자동으로 재배포합니다

## (나중에) 유료 전환 — 데이터 영구 보관 + 항상 켜짐

대리점이 자리를 잡으면 render.yaml에서 `plan: free`를 `plan: starter`(월 $7)로
바꾸고 아래 disk 설정을 services 항목에 추가한 뒤 재배포하면 됩니다:

```yaml
    disk:
      name: data
      mountPath: /var/data
      sizeGB: 1
    envVars:
      - key: DATA_DIR
        value: /var/data
```

## (참고) 로컬 테스트

```
DEMO=1 ADMIN_KEY=test python server_app.py
```
DEMO=1이면 네이버 API 없이 샘플 데이터로 화면 흐름을 확인할 수 있습니다.
