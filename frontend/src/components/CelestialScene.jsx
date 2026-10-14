import { memo } from "react";
import HongmengScene from "./HongmengScene.jsx";

// Stable, hand-composed scenery: decorative stars are not a live astronomical chart.
function random(seed) {
  let value = seed >>> 0;
  return () => {
    value = (Math.imul(value, 1664525) + 1013904223) >>> 0;
    return value / 4294967296;
  };
}
const next = random(90628);
const STARS = Array.from({ length: 240 }, (_, i) => ({
  x: 470 + next() * 1050, y: 18 + next() * 560,
  radius: i % 17 === 0 ? 1.7 : .35 + next() * .65, opacity: .15 + next() * .65,
}));
const GALAXY = Array.from({ length: 370 }, (_, i) => {
  const t = next();
  const scatter = (next() + next() + next() - 1.5) * 80;
  return { x: 760 + t * 660, y: 525 - t * 470 + Math.sin(t * Math.PI * 1.45) * 42 + scatter,
    radius: i % 21 === 0 ? 1.5 : .3 + next() * .55, opacity: .15 + next() * .48 };
});
const MANSIONS = "角 亢 氐 房 心 尾 箕 斗 牛 女 虚 危 室 壁 奎 娄 胃 昴 毕 觜 参 井 鬼 柳 星 张 翼 轸".split(" ");
const CONSTELLATIONS = [
  { name: "北斗", x: 1020, y: 170, points: [[928, 170], [969, 177], [1000, 203], [1046, 203], [1079, 231], [1062, 274], [1016, 255]] },
  { name: "天市", x: 1180, y: 300, points: [[1133, 240], [1175, 257], [1200, 304], [1168, 342], [1106, 331]] },
  { name: "太微", x: 991, y: 390, points: [[918, 322], [955, 360], [1002, 375], [1060, 353]] },
  { name: "天关", x: 900, y: 245, points: [[855, 224], [894, 256], [874, 298]] },
];
function CelestialStars({ id }) {
  return <svg className="celestial-art stars-art" data-scene="zhou-tian-stars" viewBox="0 0 1440 600" preserveAspectRatio="xMidYMid slice" aria-hidden="true" focusable="false">
    <defs>
      <linearGradient id={`${id}-night`} x2="1" y2=".8"><stop stopColor="#080d1c" /><stop offset=".55" stopColor="#11172d" /><stop offset="1" stopColor="#182340" /></linearGradient>
      <radialGradient id={`${id}-nebula`}><stop stopColor="#6b77bc" stopOpacity=".18" /><stop offset=".48" stopColor="#3d4d94" stopOpacity=".12" /><stop offset="1" stopColor="#10162d" stopOpacity="0" /></radialGradient>
      <radialGradient id={`${id}-star-glow`}><stop stopColor="#fff9df" /><stop offset=".12" stopColor="#f0d197" stopOpacity=".85" /><stop offset=".4" stopColor="#d8b471" stopOpacity=".16" /><stop offset="1" stopColor="#d8b471" stopOpacity="0" /></radialGradient>
      <linearGradient id={`${id}-orbit`} x1="0" y1="1" x2="1" y2="0"><stop stopColor="#ab8a54" stopOpacity="0" /><stop offset=".4" stopColor="#d5b781" stopOpacity=".6" /><stop offset=".75" stopColor="#fcf0cc" stopOpacity=".8" /><stop offset="1" stopColor="#ccb483" stopOpacity=".05" /></linearGradient>
      <linearGradient id={`${id}-river`} x1="0" y1="1" x2="1" y2="0"><stop stopColor="#d7b474" stopOpacity="0" /><stop offset=".5" stopColor="#b1bce1" stopOpacity=".23" /><stop offset="1" stopColor="#d7b474" stopOpacity="0" /></linearGradient>
      <filter id={`${id}-diffuse`} x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="17" /></filter>
    </defs>
    <path d="M0 0H1440V600H0Z" fill={`url(#${id}-night)`} />
    <ellipse cx="1140" cy="277" rx="490" ry="376" fill={`url(#${id}-nebula)`} />
    <g className="sky-stars">{STARS.map((s, i) => <circle key={i} cx={s.x} cy={s.y} r={s.radius} fill={i % 4 === 0 ? "#eed7a9" : "#d2d9f5"} opacity={s.opacity} />)}</g>
    <path d="M735 570C840 405 1157 402 1378 76" fill="none" stroke={`url(#${id}-river)`} strokeWidth="56" filter={`url(#${id}-diffuse)`} />
    <g className="sky-galaxy">{GALAXY.map((s, i) => <circle key={i} cx={s.x} cy={s.y} r={s.radius} fill={i % 3 === 0 ? "#dfc99a" : "#d4dcf8"} opacity={s.opacity} />)}</g>
    {/* Twenty-eight lunar mansions around the pole: an imagined Eastern sky atlas. */}
    <g className="sky-orbit" fill="none" stroke="#c1ad7f">
      <circle cx="1054" cy="274" r="207" strokeOpacity=".4" strokeWidth=".6" />
      <circle cx="1054" cy="274" r="213" strokeOpacity=".16" strokeWidth=".7" />
      <circle cx="1054" cy="274" r="225" strokeOpacity=".28" strokeWidth=".55" />
      <circle cx="1054" cy="274" r="177" strokeOpacity=".12" strokeDasharray="2 6" strokeWidth=".7" />
      {Array.from({ length: 112 }, (_, i) => <path key={i} d={`M1054 49v${i % 4 === 0 ? 9 : 3}`} transform={`rotate(${i * 360 / 112} 1054 274)`} strokeOpacity={i % 4 === 0 ? .55 : .26} strokeWidth=".75" />)}
      <ellipse cx="1054" cy="274" rx="270" ry="90" transform="rotate(-29 1054 274)" stroke={`url(#${id}-orbit)`} strokeWidth="1" />
      <ellipse cx="1054" cy="274" rx="250" ry="143" transform="rotate(54 1054 274)" strokeOpacity=".17" strokeWidth=".65" />
    </g>
    <g className="sky-mansions" fontFamily="SimSun, serif" fontSize="9" textAnchor="middle" fill="#c3b28c">
      {MANSIONS.map((name, i) => { const angle = (i / 28 * 360 - 90) * Math.PI / 180; return <text key={name} x={1054 + Math.cos(angle) * 240} y={277 + Math.sin(angle) * 240} opacity=".68">{name}</text>; })}
    </g>
    <g className="sky-constellations">
      {CONSTELLATIONS.map(c => <g key={c.name}>
        <polyline points={c.points.map(p => p.join(",")).join(" ")} fill="none" stroke="#c7bb99" strokeWidth=".75" strokeOpacity=".5" />
        {c.points.map(([x, y], i) => <g key={i}><circle cx={x} cy={y} r={i % 3 === 0 ? 8 : 5} fill={`url(#${id}-star-glow)`} opacity=".7" /><circle cx={x} cy={y} r={i % 3 === 0 ? 1.9 : 1.3} fill="#e9d9b8" /></g>)}
        <text x={c.x} y={c.y} fill="#bdbda9" fontSize="10" letterSpacing="4" fontFamily="SimSun, serif">{c.name}</text>
      </g>)}
    </g>
    <g className="sky-polaris">
      <circle cx="1042" cy="279" r="59" fill={`url(#${id}-star-glow)`} opacity=".8" />
      <circle cx="1042" cy="279" r="2.7" fill="#fff5d6" />
      <path d="M1042 258v42m-21-21h42" stroke="#f3dfb1" strokeWidth=".65" opacity=".6" />
      <circle cx="1042" cy="279" r="34" fill="none" stroke="#d0b884" strokeOpacity=".3" strokeWidth=".7" />
      <text x="1012" y="315" fill="#e1c995" fontSize="10" letterSpacing="7" fontFamily="SimSun, serif">紫微</text>
    </g>
    <g fill="none" stroke="#e0c590" strokeWidth=".7" strokeOpacity=".42">
      <path d="M802 494h51m-45 6h36m449-421h30m-25-5h20" />
      <path d="M811 507q17 0 17-12m7 12q-7 0-7-12m-7 18h14" />
      <path d="M732 326q21-13 45 0m-13-4q-1-14 9-18m-30 17q-6-10-15-8" />
    </g>
    <g className="sky-comet" opacity=".6"><path d="M1190 61 1255 28" stroke={`url(#${id}-orbit)`} strokeWidth="1.1" /><circle cx="1255" cy="28" r="1.3" fill="#f6e6bf" /></g>
    <g opacity=".25" fill="#d1ba88" fontSize="9" letterSpacing="4" fontFamily="SimSun, serif"><text x="821" y="94">北 宫 玄 武</text><text x="1267" y="489">天 河</text></g>
  </svg>;
}

function CelestialScene({ id, realm, paused }) {
  return realm === "heaven" ? <HongmengScene paused={paused} /> : <CelestialStars id={id} />;
}
export default memo(CelestialScene);
