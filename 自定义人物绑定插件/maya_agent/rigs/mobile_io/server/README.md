# Maya ↔ Android 文件服务

在 Linux 服务器上运行（目录会自动创建）：

```bash
export MAYA_MOBILE_TOKEN='请换成一段随机长令牌'
python3 maya_mobile_exchange_server.py --host :: --port 8765
```

共享目录固定默认为 `/home/wangjiafeng/电脑maya和安卓maya互通文件`，也可以用 `--root` 覆盖。Maya 电脑端填写 Linux 主机的 Tailscale MagicDNS 主机名 `http://wang.tail26a65a.ts.net:8765`；手机端使用 Caddy 提供的固定 HTTPS 反代地址 `https://lempet.top:9000/maya-mobile`，由该路径转发到本服务的 `127.0.0.1:8765`。服务本身仍保留 Tailscale 监听，方便 Maya 电脑直连。仅在可信网络使用 HTTP；公网入口应使用 HTTPS 并在服务器防火墙只放行所需端口。

服务只接受带 `X-Exchange-Token` 的请求，并只暴露 `.json` / `.mobile.json` 文件；上传采用临时文件加原子替换，不会留下半个文件。
