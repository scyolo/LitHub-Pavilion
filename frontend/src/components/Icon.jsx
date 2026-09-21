const paths = {
  radar: ["M20.2 15a9 9 0 1 1-2.7-10.2", "M16.3 14.5a5 5 0 1 1-2.5-7", "M12 12 21 3", "M12 11.9h.01"],
  grid: ["M3 3h7v7H3z", "M14 3h7v7h-7z", "M3 14h7v7H3z", "M14 14h7v7h-7z"],
  search: ["M21 21l-5-5", "M10.5 3a7.5 7.5 0 1 0 0 15 7.5 7.5 0 0 0 0-15"],
  book: ["M4 3h13a3 3 0 0 1 3 3v15H7a3 3 0 0 1-3-3V3Z", "M4 17h16", "M8 7h8", "M8 11h6"],
  building: ["M3 21h18", "M5 21V7l7-4 7 4v14", "M9 9v2", "M15 9v2", "M9 14v2", "M15 14v2"],
  sliders: ["M4 7h8", "M16 7h4", "M4 17h4", "M12 17h8", "M12 4v6", "M8 14v6"],
  arrow: ["M5 12h14", "m13 6 6 6-6 6"],
  external: ["M14 3h7v7", "m10 14 11-11", "M21 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5"],
  chevron: ["m9 5 7 7-7 7"],
  chevronDown: ["m6 9 6 6 6-6"],
  back: ["M19 12H5", "m11 6-6 6 6 6"],
  refresh: ["M20 7A8 8 0 0 0 6.2 5.5L3 9", "M3 3v6h6", "M4 17a8 8 0 0 0 13.8 1.5L21 15", "M15 15h6v6"],
  clock: ["M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18", "M12 7v5l3 2"],
  calendar: ["M5 5h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2Z", "M7 3v4", "M17 3v4", "M3 11h18"],
  link: ["M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-2 2", "M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l2-2"],
  layers: ["m12 3 10 5-10 5L2 8l10-5Z", "m2 12 10 5 10-5", "m2 16 10 5 10-5"],
  sparkles: ["m12 3 2.4 6.6L21 12l-6.6 2.4L12 21l-2.4-6.6L3 12l6.6-2.4L12 3Z", "M20 2v4", "M18 4h4"],
  bolt: ["m13 2-9 12h7l-1 8 10-13h-7l0-7Z"],
  nodes: ["M10 5a3 3 0 1 0-6 0 3 3 0 0 0 6 0", "M21 12a3 3 0 1 0-6 0 3 3 0 0 0 6 0", "M10 19a3 3 0 1 0-6 0 3 3 0 0 0 6 0", "m9 6 6 4", "m9 18 6-4", "M7 8v8"],
  scan: ["M8 3H5a2 2 0 0 0-2 2v3", "M16 3h3a2 2 0 0 1 2 2v3", "M21 16v3a2 2 0 0 1-2 2h-3", "M8 21H5a2 2 0 0 1-2-2v-3", "M7 12s2-4 5-4 5 4 5 4-2 4-5 4-5-4-5-4Z", "M12 12h.01"],
  route: ["M4 4h5v5H4z", "M15 15h5v5h-5z", "M9 6h7a4 4 0 0 1 0 8H8a3 3 0 0 0 0 6h3"],
  text: ["M4 5h16", "M4 10h16", "M4 15h11", "M4 20h8"],
  shield: ["m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Z", "m8 12 3 3 5-6"],
  check: ["m5 12 4 4L19 6"],
  close: ["m6 6 12 12", "M6 18 18 6"],
  info: ["M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18", "M12 11v6", "M12 7h.01"],
  chart: ["M4 3v17h17", "M8 15v-4", "M13 15V7", "M18 15V4"],
  copy: ["M9 9h12v12H9z", "M5 15H3V3h12v2"],
  list: ["M8 6h13", "M8 12h13", "M8 18h13", "M3 6h.01", "M3 12h.01", "M3 18h.01"],
  menu: ["M4 6h16", "M4 12h16", "M4 18h16"],
  sun: ["M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8", "M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1 1m12 12 1 1M5 19l1-1M18 6l1-1"],
  moon: ["M21 13a9 9 0 0 1-10-10 9 9 0 1 0 10 10Z"],
  bookmark: ["M6 3h12v18l-6-4-6 4V3Z"],
};

export default function Icon({ name, size = 18, className = "", ...props }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className={`icon ${className}`} {...props}>
      {(paths[name] || paths.layers).map((d, i) => <path key={i} d={d} />)}
    </svg>
  );
}
