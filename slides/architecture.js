// 실습 아키텍처 슬라이드 1장
// 기존 덱 스타일(흰 배경 · 네이비 밴드 · 파란 강조 · 다크 터미널 카드)에 맞춤
//
// 설계 원칙
//   · 화살표는 서로 붙어 있는 것끼리만. 박스를 가로지르지 않는다.
//   · 에이전트가 도는 한 바퀴는 하단 흐름 스트립으로 따로 보여준다.

const pptxgen = require("pptxgenjs");
const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.3 x 7.5

const NAVY = "17265B";
const BLUE = "1E4FD8";
const INK = "0F1D3D";
const INK2 = "1B2C55";
const PAPER = "FFFFFF";
const GREY = "6B7280";
const TEXT = "111827";

const C_CFN = "C2185B";
const C_EKS = "ED7100";
const C_BR = "01A88D";
const C_SNS = "D6336C";
const C_VPC = "7C4DFF";

const H = "Arial";
const B = "Calibri";
const M = "Consolas";

const s = pres.addSlide();
s.background = { color: PAPER };

// ── 헬퍼 ──────────────────────────────────────────────────────────────
function card(x, y, w, h, fill, line, r) {
  s.addShape(pres.ShapeType.roundRect, {
    x, y, w, h, rectRadius: r === undefined ? 0.04 : r,
    fill: { color: fill }, line: { color: line, width: 1 },
  });
}
function icon(x, y, color, letter, d) {
  d = d || 0.38;
  s.addShape(pres.ShapeType.roundRect, {
    x, y, w: d, h: d, rectRadius: 0.11, fill: { color }, line: { color, width: 0 },
  });
  s.addText(letter, {
    x, y, w: d, h: d, fontFace: H, fontSize: d * 29, bold: true, color: PAPER,
    align: "center", valign: "middle", margin: 0,
  });
}
function label(x, y, w, t, o) {
  o = o || {};
  s.addText(t, {
    x, y, w, h: o.h || 0.24, fontFace: o.mono ? M : B, fontSize: o.size || 11,
    bold: o.bold || false, color: o.color || TEXT, align: o.align || "left",
    lineSpacing: o.ls || 14, margin: 0, valign: "top",
  });
}
function arrow(x, y, w, h, color, dash) {
  s.addShape(pres.ShapeType.line, {
    x, y, w, h,
    line: { color, width: 1.8, endArrowType: "triangle", dashType: dash || "solid" },
  });
}

// ── 헤더 ──────────────────────────────────────────────────────────────
s.addShape(pres.ShapeType.ellipse, { x: 0.72, y: 0.42, w: 0.08, h: 0.08, fill: { color: BLUE } });
label(0.86, 0.34, 5, "5 · 실습 · LLM 에이전트", { size: 10, bold: true, color: BLUE });
label(11.2, 0.34, 1.4, "45 / 46", { size: 10, color: "9CA3AF", align: "right" });

s.addText("실습 아키텍처 — 내 AWS 계정에 만들어지는 것", {
  x: 0.72, y: 0.6, w: 11.9, h: 0.66, fontFace: H, fontSize: 29, bold: true, color: TEXT, margin: 0,
});
s.addShape(pres.ShapeType.line, { x: 0.72, y: 1.36, w: 0.62, h: 0, line: { color: BLUE, width: 3 } });
label(0.72, 1.5, 11.9, "CloudFormation 한 번으로 전부 생성됩니다. 아래 여섯 단계가 에이전트가 도는 한 바퀴입니다.", {
  size: 13, color: GREY,
});

// ══════════════════════════════════════════════════════════════════════
// 좌측 — 내 노트북
// ══════════════════════════════════════════════════════════════════════
card(0.72, 1.98, 2.48, 3.42, INK, INK, 0.06);
s.addShape(pres.ShapeType.ellipse, { x: 0.94, y: 2.17, w: 0.09, h: 0.09, fill: { color: "FF5F57" } });
s.addShape(pres.ShapeType.ellipse, { x: 1.1, y: 2.17, w: 0.09, h: 0.09, fill: { color: "FEBC2E" } });
s.addShape(pres.ShapeType.ellipse, { x: 1.26, y: 2.17, w: 0.09, h: 0.09, fill: { color: "28C840" } });
label(1.5, 2.13, 1.5, "내 노트북", { color: "C7D2E8", size: 10 });

card(0.94, 2.46, 2.04, 2.72, INK2, "2B3C68");
const scripts = [
  ["deploy_lab.py", "인프라 생성"],
  ["break_it.py", "장애 주입"],
  ["agent.py", "에이전트 루프"],
  ["tools.py", "도구 7개"],
  ["k8s.py", "EKS 인증 · REST"],
  ["status.py", "상태 확인"],
  ["cleanup.py", "전부 삭제"],
];
let sy = 2.6;
scripts.forEach(([f, d]) => {
  label(1.12, sy, 1.72, f, { mono: true, size: 9, color: "E8EDF8", h: 0.15 });
  label(1.12, sy + 0.16, 1.72, d, { size: 8.2, color: "7E93C4", h: 0.14 });
  sy += 0.37;
});

// ══════════════════════════════════════════════════════════════════════
// AWS 계정 경계
// ══════════════════════════════════════════════════════════════════════
s.addShape(pres.ShapeType.roundRect, {
  x: 3.66, y: 1.9, w: 8.96, h: 3.58, rectRadius: 0.02,
  fill: { color: PAPER }, line: { color: "9AA7C4", width: 1.25, dashType: "dash" },
});
label(3.86, 1.97, 5, "AWS 계정  ·  ap-northeast-2", { size: 9.5, bold: true, color: "5B6B90" });

// ── CloudFormation 띠 ─────────────────────────────────────────────────
card(3.88, 2.26, 8.5, 0.56, "FCEEF4", "F0C8DA");
icon(4.04, 2.35, C_CFN, "C", 0.38);
label(4.54, 2.35, 3.0, "CloudFormation", { bold: true, size: 12, color: "8E1247", h: 0.2 });
label(4.54, 2.57, 4.6, "VPC · EKS · SNS 를 한 번에 생성하고 한 번에 삭제", { size: 9.2, color: "A8567F", h: 0.16 });
label(9.5, 2.44, 2.7, "python deploy_lab.py", { mono: true, size: 9, color: "8E1247", align: "right" });

// ── VPC ───────────────────────────────────────────────────────────────
s.addShape(pres.ShapeType.roundRect, {
  x: 3.88, y: 2.94, w: 5.42, h: 2.4, rectRadius: 0.03,
  fill: { color: "FAF8FF" }, line: { color: "C9B6FF", width: 1 },
});
icon(4.02, 3.02, C_VPC, "V", 0.26);
label(4.36, 3.04, 3.2, "VPC   10.42.0.0/16", { size: 9, bold: true, color: "5B3BB5" });

// ── EKS ───────────────────────────────────────────────────────────────
card(4.06, 3.34, 5.06, 1.9, "FFF7F0", "F5D3B4");
icon(4.2, 3.43, C_EKS, "K", 0.32);
label(4.62, 3.42, 3.2, "EKS Auto Mode", { bold: true, size: 11.5, color: "9A4A00", h: 0.2 });
label(4.62, 3.64, 4.2, "노드 자동 프로비저닝", { size: 8.5, color: "B87333", h: 0.16 });

const ns = [
  ["argocd", "ArgoCD", "Git 을 감시해 클러스터에 적용", "1F6FEB"],
  ["git", "Gitea", "앱 매니페스트 저장소 · REST API", "2E7D32"],
  ["kdt-dev", "kdt-dev-api", "실제 앱 — nginx ×2", "C2185B"],
];
let ny = 3.86;
ns.forEach(([n, app, desc, col]) => {
  card(4.2, ny, 4.78, 0.42, PAPER, "E6D5C2");
  s.addShape(pres.ShapeType.roundRect, {
    x: 4.31, y: ny + 0.1, w: 0.8, h: 0.22, rectRadius: 0.05, fill: { color: col },
  });
  s.addText(n, {
    x: 4.31, y: ny + 0.1, w: 0.8, h: 0.22, fontFace: M, fontSize: 7, bold: true,
    color: PAPER, align: "center", valign: "middle", margin: 0,
  });
  label(5.24, ny + 0.07, 1.2, app, { bold: true, size: 10, h: 0.2 });
  label(6.5, ny + 0.09, 2.4, desc, { size: 8.4, color: GREY, h: 0.18 });
  ny += 0.48;
});

// ArgoCD → 앱  (GitOps, 내부 흐름 · 짧은 화살표)
arrow(9.05, 4.05, 0, 0.86, "1F6FEB", "dash");
label(8.98, 4.32, 0.34, "G\ni\nt\nO\np\ns", { size: 6, color: "1F6FEB", align: "center", ls: 7, h: 0.5 });

// ── 우측 — Bedrock · SNS ──────────────────────────────────────────────
card(9.62, 2.94, 2.76, 1.14, "EEFBF8", "B8E8DF");
icon(9.8, 3.06, C_BR, "B", 0.38);
label(10.3, 3.08, 2.0, "Bedrock", { bold: true, size: 12, color: "00695C" });
label(9.8, 3.5, 2.4, "Claude Haiku 4.5", { mono: true, size: 8.6, color: "00897B", h: 0.16 });
label(9.8, 3.7, 2.4, "Converse API · Tool Use", { size: 8.6, color: "4DB6AC", h: 0.16 });

card(9.62, 4.2, 2.76, 1.14, "FDEEF3", "F4C6D6");
icon(9.8, 4.32, C_SNS, "S", 0.38);
label(10.3, 4.34, 2.0, "SNS", { bold: true, size: 12, color: "AD1457" });
label(9.8, 4.76, 2.4, "진단 리포트 발송", { size: 8.6, color: "D6336C", h: 0.16 });
label(9.8, 4.96, 2.4, "→ 담당자 이메일", { size: 8.6, color: "E091B0", h: 0.16 });

// ── 붙어 있는 것끼리만 화살표 ─────────────────────────────────────────
// 노트북 → CloudFormation
arrow(3.24, 2.54, 0.58, 0, C_CFN);
// 노트북 → VPC(EKS · Git)
arrow(3.24, 4.1, 0.58, 0, C_EKS);
// 노트북 ↔ Bedrock 은 거리가 멀어 화살표 대신 아래 흐름 스트립으로 표현

// ══════════════════════════════════════════════════════════════════════
// 하단 — 에이전트가 도는 한 바퀴
// ══════════════════════════════════════════════════════════════════════
const flow = [
  ["1", "장애 주입", "매니페스트를 Gitea 에 실제 커밋", C_EKS],
  ["2", "ArgoCD 적용", "30초 안에 동기화 → pod 가 진짜로 죽음", "1F6FEB"],
  ["3", "대화 전송", "도구 목록 + 대화를 Bedrock 에", C_BR],
  ["4", "도구 호출 요청", "모델은 “불러줘”라고 말만 함", C_BR],
  ["5", "실제 API 호출", "K8s · Git — 내 코드가 실행", C_EKS],
  ["6", "리포트 발송", "SNS → 이메일 · 사람 승인 필요", C_SNS],
];
let fx = 0.72;
const fw = 1.9;
flow.forEach(([n, t, d, col], i) => {
  card(fx, 5.68, fw, 0.76, "F6F8FC", "DFE5F0");
  s.addShape(pres.ShapeType.ellipse, { x: fx + 0.14, y: 5.79, w: 0.26, h: 0.26, fill: { color: col } });
  s.addText(n, {
    x: fx + 0.14, y: 5.79, w: 0.26, h: 0.26, fontFace: H, fontSize: 9.5, bold: true,
    color: PAPER, align: "center", valign: "middle", margin: 0,
  });
  label(fx + 0.48, 5.8, fw - 0.6, t, { bold: true, size: 9.6, h: 0.22 });
  label(fx + 0.14, 6.08, fw - 0.28, d, { size: 8.1, color: GREY, ls: 10, h: 0.3 });
  if (i < flow.length - 1) arrow(fx + fw + 0.02, 6.06, 0.16, 0, "9AA7C4");
  fx += fw + 0.2;
});

// ── 하단 밴드 ─────────────────────────────────────────────────────────
s.addShape(pres.ShapeType.roundRect, {
  x: 0.72, y: 6.62, w: 11.9, h: 0.6, rectRadius: 0.05,
  fill: { color: NAVY }, line: { color: NAVY, width: 0 },
});
s.addText(
  "LLM 은 클러스터에 접속하지 않습니다. 도구를 불러달라고 요청할 뿐이고, 실제 호출과 자격증명은 내 코드가 쥡니다.",
  { x: 1.05, y: 6.62, w: 11.2, h: 0.6, fontFace: B, fontSize: 13.5, bold: true, color: PAPER, valign: "middle", margin: 0 }
);

s.addNotes(
  "이 한 장이 실습 전체의 지도입니다.\n\n" +
  "위쪽 그림 — 무엇이 만들어지는가\n" +
  "  CloudFormation 이 VPC · EKS Auto Mode · SNS 를 한 번에 만든다 (25~35분).\n" +
  "  EKS 안에는 네임스페이스 세 개. ArgoCD · Gitea · 실제 앱.\n" +
  "  Bedrock 과 SNS 는 VPC 밖의 관리형 서비스다.\n\n" +
  "아래쪽 여섯 단계 — 어떻게 도는가\n" +
  "  1~2 는 GitOps. 커밋이 곧 배포이고, 그래서 장애도 커밋으로 만든다.\n" +
  "  3~5 가 Tool Use 의 전부다. 4번과 5번 사이가 이 강의의 핵심 경계.\n" +
  "  6 은 쓰기 작업이라 사람 승인을 받는다.\n\n" +
  "하단 문장에서 3초 멈출 것. DevOps 청중의 보안 우려가 여기서 풀린다."
);

pres.writeFile({ fileName: "/home/claude/lab2/slides/실습_아키텍처.pptx" }).then(() => {
  console.log("작성 완료");
});
