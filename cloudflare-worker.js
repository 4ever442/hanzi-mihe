// Cloudflare Worker：反代到 Render 上的 FastAPI 后端
// 用途：拿到免费的 xxx.workers.dev 子域，并把请求转发到 Render 服务
// 部署：Cloudflare 控制台 → Workers & Pages → Create Worker → 把本文件内容贴进去
// 改 ONRENDER 为你在 Render 上的服务子域（形如 hanzi-mihe-abc.onrender.com）

const ONRENDER = "你的服务名.onrender.com"; // ← 替换成你的 Render 服务名

export default {
  async fetch(req) {
    const url = new URL(req.url);

    // 保留原始路径、查询串、请求方法
    const target = `https://${ONRENDER}${url.pathname}${url.search}`;

    const headers = new Headers(req.headers);
    headers.set("Host", ONRENDER);

    const proxied = new Request(target, {
      method: req.method,
      headers,
      body: ["POST", "PUT", "PATCH"].includes(req.method) ? req.body : undefined,
      redirect: "manual",
    });

    const res = await fetch(proxied);

    // Render 休眠冷启动时可能返回 503 + Retry-After，简单透传
    const outHeaders = new Headers(res.headers);
    outHeaders.set("Access-Control-Allow-Origin", "*");

    return new Response(res.body, { status: res.status, headers: outHeaders });
  },
};
