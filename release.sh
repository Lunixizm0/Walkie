#!/usr/bin/env bash
set -euo pipefail

VERSION="${1:?Kullanim: ./release.sh 1.0.0}"
TAG="v${VERSION}"

echo "pyproject.toml güncelleniyor..."
sed -i "s/^version = .*/version = \"${VERSION}\"/" pyproject.toml

echo "Testler çalıştırılıyor..."
uv run pytest tests/ -v

echo "Commit ediliyor..."
git add pyproject.toml
git diff --cached --quiet || git commit -m "release: ${TAG}"

echo "Tag oluşturuluyor..."
git tag -f "${TAG}"

echo "Push ediliyor..."
git push origin master "${TAG}" --force

echo "GitHub Release oluşturuluyor..."
gh release delete "${TAG}" --yes --cleanup-tag 2>/dev/null || true
gh release create "${TAG}" \
  --title "${TAG}" \
  --generate-notes

echo ""
echo "${TAG} yayınlandı! GitHub Actions PyPI'ya yüklüyor."
echo "https://github.com/Lunixizm0/walkie/actions"
echo "https://pypi.org/project/walkie/${VERSION}/"

echo ""
echo "PyPI üzerinde ${VERSION} versiyonu bekleniyor..."

PYPI_URL="https://pypi.org/pypi/walkie/${VERSION}/json"
MAX_ATTEMPTS=30
SLEEP_SECONDS=5

for ((i=1; i<=MAX_ATTEMPTS; i++)); do
    HTTP_STATUS=$(curl -sS -o /dev/null -w "%{http_code}" "$PYPI_URL")

    if [[ "$HTTP_STATUS" == "200" ]]; then
        echo "+ ${VERSION} PyPI'da mevcut"
        echo "https://pypi.org/project/walkie/${VERSION}/"
        exit 0
    fi

    echo "  Henüz mevcut değil (HTTP ${HTTP_STATUS}). ${SLEEP_SECONDS}s bekleniyor... [$i/$MAX_ATTEMPTS]"
    sleep "$SLEEP_SECONDS"
done

echo ""
echo "${VERSION} ${MAX_ATTEMPTS} denemeden sonra PyPI'da bulunamadı."
echo "GitHub Actions kontrol et:"
echo "https://github.com/Lunixizm0/walkie/actions"

exit 1
