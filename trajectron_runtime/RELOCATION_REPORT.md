# 런타임 코드 이동 결과

작업일: 2026-10-12. 브랜치: `experiment/trajectron-inference`.

## 배치와 변경

기존 `src/baselines/trajectron_runtime/`의 구현 파일 14개를
`src/baselines/Trajectron-plus-plus/trajectron_runtime/`으로 이동했다.
이동 전에 모든 구현 파일을 복사하고 SHA-256 일치를 확인했다.

기존 외부 디렉터리에는 로그, 결과, 백업, 이미지 복구 아카이브를 그대로
보관한다. 과거 로그/manifest에 저장된 절대 경로는 역사적 기록이므로 변경하지
않았다. 현재 생성 데이터도 이 외부 디렉터리를 기본값으로 사용한다.

- `runtime_paths.py`: checkout 위치로부터 소스와 외부 상태 경로를 계산한다.
  checkout 내부에 생성 데이터를 기록하는 경로는 거부한다.
- `verify_container.py`: 기본 소스는 런타임의 부모 checkout이며, 결과와
  중첩 Docker 명령 로그는 선택한 외부 상태 경로에 기록한다.
- `run_logged.py`: 외부 로그를 사용하며 `--state-root`, `--log-dir`를 지원한다.
- `backup_file.py`, `archive_image.py`: 백업/이미지를 외부 상태에 저장한다.
  이미지 내보내기는 `--artifact-dir`로 저장 위치를 별도 지정할 수 있다.
- `snapshot_host.py`: `--workspace-root`를 명시적으로 받아 검사 범위를 유지한다.
  런타임 구현과 외부 상태를 비교 대상에서 제외한다.
- `audit_preservation.py`: 외부 snapshot/report 경로를 사용한다.
- README와 최초 구현 보고서: 실행 명령과 외부 증거 링크를 갱신했다.

`--state-root` > `TRAJECTRON_RUNTIME_STATE` > checkout의 형제 디렉터리
`trajectron_runtime/` 순서로 상태 경로를 선택한다. 개별 저장 경로 옵션은 해당
대상을 별도로 지정한다. 경로 계산은 실행 중인 작업 디렉터리에 의존하지 않는다.

Dockerfile, requirements.lock, .dockerignore와 컨테이너 validator는 최초
구현과 SHA-256이 동일하다. 이미지 재빌드는 필요하지 않았으며 기존 이미지를
재사용했다. 컨테이너 마운트/보안/자원 제한도 유지했다. 생성 데이터는 소스
마운트에 포함되지 않고 새 결과 디렉터리만 별도로 쓰기 가능하게 연결된다.

## 검증

- `/tmp`에서 이동한 launcher를 절대 경로로 실행: 종료 코드 0.
- [컨테이너 보고서](../../trajectron_runtime/results/20261012T082716.365419Z/dependency-report.json):
  **passed**, 의존성/모델 초기화 검증 32개 통과.
- [실행 manifest](../../trajectron_runtime/results/20261012T082716.365419Z/launch-manifest.json):
  소스는 Trajectron++ checkout 읽기 전용, 결과는 외부 상태 경로 쓰기 가능.
- 환경 변수로 바꾼 로그 경로와 CLI로 바꾼 백업 경로: 실제 파일 생성 확인.
- Python 문법, 기본 경로, checkout 내부 저장 경로 거부, Git ignore 규칙 확인.
- [호스트 보존 보고서](../../trajectron_runtime/logs/relocation-preservation-report.json):
  기존 파일 885개 변경/삭제 없음, 호스트 Python identity 및 distribution
  136개의 이름/버전 동일. 원시 전후 snapshot도 동일하다.
- 기존 Git tracked 파일 변경 없음. 새 런타임 파일은 Git에서 untracked로 보이며,
  이번 작업에서 stage, commit, push는 수행하지 않았다.

G1 어댑터, 실험 데이터 예측과 GPU 실행은 이번 이동 검증에 포함하지 않는다.
새 상태 경로로 이미지 아카이브를 다시 내보내거나 기존 아카이브를 load하지 않았다.

## 기록과 복구

[명령 journal](../../trajectron_runtime/logs/commands.jsonl)에 명령과 결과를 기록했다.
[이동 manifest](../../trajectron_runtime/logs/relocation-manifest.json)에 기존/새 파일 경로,
이동 전 hash와 백업 위치가 있다. 최종 파일 hash와 변경 diff는 외부
`logs/relocation-completion.json`, `logs/relocation-changes.patch`에 기록한다.

원본 구현 백업:

```text
src/baselines/trajectron_runtime/backups/20261012T082352.407546Z_relocation/
```

원래 구현으로 복귀하려면 manifest의 `backup` 파일들을 `original` 경로로
복사한다. 원래 실행 명령은 `src`에서 다음과 같다:

```bash
python3 -B baselines/trajectron_runtime/run_logged.py --label verify-restored-runtime -- \
  python3 -B baselines/trajectron_runtime/verify_container.py
```

복귀 시 먼저 백업 hash와 복사 대상의 상태를 확인하고 복사 작업도 로그로
기록해야 한다. 새 checkout 내부 파일을 삭제할 필요는 없다. 이 복귀 절차를
이번 작업에서 실제 실행하지 않았다.

기존 이미지 복구 아카이브는 이동하지 않았다:

```text
src/baselines/trajectron_runtime/artifacts/g1-trajectron-int-ee-cpu-py36-20261012T080237.178963Z.tar
SHA-256: efcd1f4986026bfeece5d11487aa6a63f58fb5e30b37c5247fd868a9d473dc8c
```

이미지 및 캐시 삭제, Docker prune, 호스트 Python/ROS 설치 또는 설정 변경은
수행하지 않았다.
