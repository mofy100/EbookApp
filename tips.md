# ファイルのコピー方法
# remote -> local
rsync -av --relative kvmhv12:app/EbookApp/backend/data/.\*/summary_qwen.json backend/data/
# local -> remote
rsync -av --relative backend/data/./*/summary_qwen.json sakura:EbookApp/