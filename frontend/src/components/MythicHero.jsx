import { useEffect, useId, useRef, useState } from "react";
import { Link } from "react-router-dom";
import Icon from "./Icon.jsx";
import CelestialScene from "./CelestialScene.jsx";
import "./MythicHero.css";
import "./HongmengScene.css";

/** Two different mythic scenes, synchronized with the whole-site theme. */
export default function MythicHero({ theme = "dark", onThemeChange }) {
  const id = useId().replace(/:/g, "");
  const realm = theme === "light" ? "heaven" : "stars";
  const heavenly = realm === "heaven";
  const cover = useRef(null);
  const [paused, setPaused] = useState(false);
  const [reduced, setReduced] = useState(() => globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false);
  const [offscreen, setOffscreen] = useState(false);
  const [hidden, setHidden] = useState(() => document.visibilityState === "hidden");

  useEffect(() => {
    const preference = globalThis.matchMedia?.("(prefers-reduced-motion: reduce)");
    const onPreference = (event) => setReduced(event.matches);
    const onVisibility = () => setHidden(document.visibilityState === "hidden");
    preference?.addEventListener?.("change", onPreference);
    document.addEventListener("visibilitychange", onVisibility);
    const observer = typeof IntersectionObserver === "function"
      ? new IntersectionObserver(([entry]) => setOffscreen(!entry.isIntersecting), { threshold: 0 }) : null;
    if (cover.current) observer?.observe(cover.current);
    return () => {
      preference?.removeEventListener?.("change", onPreference);
      document.removeEventListener("visibilitychange", onVisibility);
      observer?.disconnect();
    };
  }, []);

  const motionPaused = paused || reduced || offscreen || hidden;

  return <section ref={cover} className="mythic-hero" aria-label="海纳百川 · 东方神话封面" data-realm={realm}
    data-motion={motionPaused ? "paused" : "running"}>
    <CelestialScene id={`celestial-${id}`} realm={realm} paused={motionPaused} />
    <div className="mythic-shade" aria-hidden="true" />
    <div className="mythic-header">
      <div className="mythic-edition"><span className="mythic-emblem" aria-hidden="true">藏</span><span><b>LITHUB PAVILION</b><i /><em>东方藏书阁</em></span></div>
      {onThemeChange && <div className="realm-switch" role="group" aria-label="封面意境与网站主题">
        <button type="button" aria-label="切换至鸿蒙云海" aria-pressed={heavenly} onClick={() => onThemeChange("light")}><Icon name="sun" size={13} /><span>云海</span></button>
        <button type="button" aria-label="切换至周天星空" aria-pressed={!heavenly} onClick={() => onThemeChange("dark")}><Icon name="moon" size={13} /><span>星穹</span></button>
      </div>}
    </div>
    <div className="mythic-copy">
      <div className="mythic-eyebrow"><span />{heavenly ? "鸿 蒙 云 海" : "周 天 星 藏"}<i>{heavenly ? "WHERE ALL RIVERS BECOME ONE" : "THE CELESTIAL SPHERE"}</i></div>
      <h1>海纳百川<span>万卷归藏</span></h1>
      <p className="mythic-description">{heavenly ? "天地无垠，万流同归。" : "以星河为引，向未知而行。"}<br /><span>{heavenly ? "以无尽之境，纳万象新知。" : "汇百家之言，藏天下之知。"}</span></p>
      <div className="mythic-actions">
        <Link to="/papers" className="mythic-primary">探索论文<Icon name="arrow" size={17} /></Link>
        <Link to="/venues" className="mythic-secondary">浏览来源<Icon name="arrow" size={15} /></Link>
      </div>
    </div>
    <div className="mythic-colophon" aria-hidden="true"><span>{heavenly ? "万流同归 · 天地无垠" : "三垣列宿 · 万象同辉"}</span><i /><span>{heavenly ? "海纳百川，有容乃大" : "星汉灿烂，求知不息"}</span></div>
    <div className="mythic-footer">
      <div className="mythic-scene-caption"><span className="mythic-chapter">{heavenly ? "01" : "02"}</span><span>{heavenly ? "鸿蒙云海" : "周天星空"}<small>{heavenly ? "ALL RIVERS RETURN TO THE BOUNDLESS" : "CONSTELLATIONS BEYOND THE HORIZON"}</small></span></div>
      <button type="button" className="mythic-motion" aria-label={reduced ? "系统已减少动态效果" : paused ? "播放封面动画" : "暂停封面动画"}
        aria-pressed={paused || reduced} disabled={reduced} title={reduced ? "遵循系统的减少动态效果设置" : undefined} onClick={() => setPaused(value => !value)}>
        <svg width="11" height="11" viewBox="0 0 12 12" aria-hidden="true" fill="currentColor">
          {paused || reduced ? <path d="M3 1.5 10 6 3 10.5Z" /> : <path d="M2.5 2h2v8h-2zM7.5 2h2v8h-2z" />}
        </svg><span>{reduced ? "静态意境" : paused ? "播放动效" : "暂停动效"}</span>
      </button>
    </div>
  </section>;
}
