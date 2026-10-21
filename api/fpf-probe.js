module.exports = async function handler(req, res) {
  if (req.method !== "GET") {
    res.setHeader("Allow", "GET");
    return res.status(405).json({ error: "Method not allowed" });
  }

  const url = "https://resultados.fpf.pt/Competition/Details?competitionId=22591&seasonId=102";
  try {
    const response = await fetch(url, {
      redirect: "follow",
      headers: {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
        "Referer": "https://resultados.fpf.pt/",
        "Cache-Control": "no-cache"
      },
      signal: AbortSignal.timeout(12000)
    });
    const body = await response.text();
    const title = (body.match(/<title[^>]*>([\\s\\S]*?)<\\/title>/i) || [])[1] || "";
    const hasCompetition = /LIGA AFP|CARLOS ALBERTO|SUB.?6|Dragon Force|Grupo Vermelho/i.test(body);
    const challenge = /cloudflare|captcha|access denied|forbidden|request blocked|attention required/i.test(body);
    res.setHeader("Cache-Control", "no-store");
    res.setHeader("Access-Control-Allow-Origin", "https://manuelpinto2022.vercel.app");
    return res.status(200).json({
      upstreamStatus: response.status,
      finalUrl: response.url,
      contentType: response.headers.get("content-type"),
      bodyLength: body.length,
      title: title.replace(/<[^>]+>/g, "").trim().slice(0, 180),
      hasCompetition,
      looksLikeBotChallenge: challenge,
      preview: body.slice(0, 100).replace(/\\s+/g, " ")
    });
  } catch (error) {
    res.setHeader("Cache-Control", "no-store");
    return res.status(200).json({
      probeError: String(error && error.message ? error.message : error)
    });
  }
};
