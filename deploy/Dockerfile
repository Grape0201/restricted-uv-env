FROM nginx:alpine

# Nginx のデフォルト歓迎ページ設定を削除
RUN rm -f /etc/nginx/conf.d/default.conf

# uv ミラー用設定を配置
COPY nginx-uv-mirror.conf /etc/nginx/conf.d/uv-mirror.conf

# 公開ルートディレクトリを作成
RUN mkdir -p /var/www/uv-mirror

EXPOSE 80

# コンテナ停止シグナル対応
STOPSIGNAL SIGQUIT

CMD ["nginx", "-g", "daemon off;"]
