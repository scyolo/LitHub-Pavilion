import { Component, Suspense, useEffect, useState } from "react";
import { NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "./api.js";
import { useCrawlStatus } from "./hooks/useResearchData.js";
import { formatDate, paperHref, prioritizeDirections, topic } from "./lib/presentation.js";
import { APP_NAME, APP_DESCRIPTION } from "./lib/brand.js";
import Icon from "./components/Icon.jsx";
import SearchInput from "./components/SearchInput.jsx";
import PageScroll from "./components/PageScroll.jsx";
import { LoadingState } from "./components/States.jsx";

import { createPageModule } from "./lib/lazy-page.js";
import Home from "./pages/Home.jsx";
const pages = {
  deadlines: createPageModule(() => import("./pages/Deadlines.jsx")),
  papers: createPageModule(() => import("./pages/PaperList.jsx")),
  detail: createPageModule(() => import("./pages/PaperDetail.jsx")),
  coverage: createPageModule(() => import("./pages/SourceCoverage.jsx")),
  venues: createPageModule(() => import("./pages/Venues.jsx")),
  admin: createPageModule(() => import("./pages/Admin.jsx")),
};
const { Component: Deadlines } = pages.deadlines, { Component: PaperList } = pages.papers;
const { Component: PaperDetail } = pages.detail, { Component: SourceCoverage } = pages.coverage;
const { Component: Venues } = pages.venues, { Component: Admin } = pages.admin;
const preloadPage = page => { page?.preload().catch(() => {}); };

const NAVIGATION = [
  { to: "/", name: "研究总览", icon: "grid", end: true },
  { to: "/papers", name: "论文探索", icon: "book", page: pages.papers },
  { to: "/venues", name: "会议与期刊", icon: "building", page: pages.venues },
  { to: "/deadlines", name: "截稿日历", icon: "calendar", page: pages.deadlines },
];

function initialTheme() {
  try { return localStorage.getItem("papertracker-theme") === "light" ? "light" : "dark"; } catch { return "dark"; }
}

class PageBoundary extends Component {
  state = { error: false };
  static getDerivedStateFromError() { return { error: true }; }
  render() {
    if (this.state.error) return <div className="state-box" role="alert"><Icon name="info" size={30} /><h2>页面暂时无法显示</h2><p>请刷新页面重试。已保存的论文数据不会丢失。</p><button className="button primary" onClick={() => window.location.reload()}>刷新页面</button></div>;
    return this.props.children;
  }
}

export default function App() {
  const location = useLocation();
  const navigate = useNavigate();
  const [theme, setTheme] = useState(initialTheme);
  const [menuOpen, setMenuOpen] = useState(false);
  const { data: crawl } = useCrawlStatus();
  const { data: directions } = useQuery({ queryKey: ["directions"], queryFn: ({ signal }) => api.directions(signal) });
  const pageName = location.pathname.startsWith("/coverage") ? "来源覆盖核验" : location.pathname.startsWith("/deadlines") ? "截稿日历" : location.pathname.startsWith("/admin") ? (api.isSnapshot ? "快照与更新" : "采集管理") : location.pathname.startsWith("/venues") ? "会议与期刊" : location.pathname.startsWith("/papers/") ? "论文详情" : location.pathname.startsWith("/papers") ? "论文探索" : "研究总览";

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem("papertracker-theme", theme); } catch { /* Storage may be disabled in private browsing. */ }
  }, [theme]);
  useEffect(() => { setMenuOpen(false); }, [location.pathname, location.search]);
  useEffect(() => { document.title = `${pageName} · ${APP_NAME}`; }, [pageName]);
  useEffect(() => {
    function onKey(event) {
      if (event.key === "/" && !["INPUT", "TEXTAREA", "SELECT"].includes(event.target.tagName) && !event.target.isContentEditable) {
        event.preventDefault(); document.querySelector('[aria-label="全局检索论文"]')?.focus();
      }
      if (event.key === "Escape") setMenuOpen(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="app-shell">
      <PageScroll />
      <a className="skip-link" href="#main-content" onClick={(event) => { event.preventDefault(); document.getElementById("main-content")?.focus(); }}>跳转至主要内容</a>
      {menuOpen && <button className="sidebar-backdrop" aria-label="关闭导航" onClick={() => setMenuOpen(false)} />}
      <aside className={`sidebar ${menuOpen ? "open" : ""}`} aria-label="主导航">
        <NavLink to="/" className="brand"><span className="brand-symbol"><Icon name="pavilion" size={27} /></span><span className="brand-copy"><strong>{APP_NAME}</strong><small>{APP_DESCRIPTION}</small></span></NavLink>
        <div className="workspace-label"><span className="status-dot" />个人研究空间<span className="local-tag">{api.isSnapshot ? "SNAPSHOT" : "LOCAL"}</span></div>
        <div className="nav-section-title">工作台 <span>WORKSPACE</span></div>
        <nav className="main-nav">{NAVIGATION.map((item) => <NavLink key={item.to} onPointerEnter={() => preloadPage(item.page)} onFocus={() => preloadPage(item.page)} to={item.to} end={item.end} className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}><Icon name={item.icon} size={19} /><span>{item.name}</span><Icon name="chevron" size={13} /></NavLink>)}</nav>
        <div className="nav-section-title topic-nav-heading">研究方向 <span>TOPICS</span></div>
        <nav className="topic-nav" aria-label="按研究方向浏览">{prioritizeDirections(directions?.items || []).map((d) => {
          const t = topic(d.code, d.name);
          const selected = new URLSearchParams(location.search).get("direction")?.split(",").includes(d.code);
          return <NavLink key={d.code} onPointerEnter={() => preloadPage(pages.papers)} onFocus={() => preloadPage(pages.papers)} to={paperHref(null, { direction: d.code })} className={`topic-nav-link ${selected && location.pathname === "/papers" ? "selected" : ""}`}><span className="topic-dot" style={{ background: t.color }} />{d.name}</NavLink>;
        })}</nav>
        <div className="sidebar-bottom">
          <NavLink to="/admin" onPointerEnter={() => preloadPage(pages.admin)} onFocus={() => preloadPage(pages.admin)} className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}><Icon name="sliders" size={19} /><span>{api.isSnapshot ? "快照与更新" : "采集管理"}</span><Icon name="chevron" size={13} /></NavLink>
          <div className="sidebar-note"><Icon name="shield" size={16} /><div><strong>仅追踪 CCF A / B</strong><p>保留元数据与官方链接<br />不下载、不存储 PDF</p></div></div>
          <div className="sidebar-footer"><span className="avatar">R</span><div><strong>Researcher</strong><small>专注下一篇好论文</small></div><span className="online-dot" /></div>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <button className="icon-button mobile-menu" aria-label="打开导航" aria-expanded={menuOpen} onClick={() => setMenuOpen(!menuOpen)}><Icon name="menu" size={21} /></button>
          <div className="breadcrumb">工作台 <Icon name="chevron" size={12} /><span>{pageName}</span></div>
          <div className="topbar-search"><SearchInput key={location.pathname} automatic={false} label="全局检索论文" placeholder="模糊检索论文 · 不区分大小写…" onCommit={(q) => navigate(paperHref(null, { q }))} /></div>
          <span className={`topbar-sync ${crawl?.running ? "busy" : ""}`}><span className="status-dot" />{api.isSnapshot ? "快照浏览" : crawl?.running ? "正在同步" : "本地模式"}</span>
          <button className="icon-button theme-toggle" title={theme === "dark" ? "切换浅色主题" : "切换深色主题"} aria-label={theme === "dark" ? "切换浅色主题" : "切换深色主题"} onClick={() => setTheme(theme === "dark" ? "light" : "dark")}><Icon name={theme === "dark" ? "sun" : "moon"} size={17} /><span className="theme-label">{theme === "dark" ? "鸿蒙云海" : "周天星空"}</span></button>
        </header>
        <main id="main-content" className="page-content" tabIndex={-1}>
          <PageBoundary key={location.pathname}><Suspense fallback={<LoadingState />}><Routes>
            <Route path="/" element={<Home theme={theme} onThemeChange={setTheme} />} /><Route path="/papers" element={<PaperList />} /><Route path="/papers/:id" element={<PaperDetail />} />
            <Route path="/venues" element={<Venues />} /><Route path="/coverage" element={<SourceCoverage />} /><Route path="/deadlines" element={<Deadlines />} /><Route path="/admin" element={<Admin />} />
            <Route path="*" element={<div className="state-box"><h1>这个页面不存在</h1><NavLink to="/" className="button primary">返回研究总览</NavLink></div>} />
          </Routes></Suspense></PageBoundary>
        </main>
        <footer className="page-footer"><span>{APP_NAME} <span>·</span> {APP_DESCRIPTION}</span><span>{api.isSnapshot ? `公开快照 · CCF A/B 配置目录 · ${formatDate(crawl?.generated_at)}` : `本地数据 · CCF A/B 配置目录 · ${crawl?.schedule?.next_crawl_at ? `下次采集 ${formatDate(crawl.schedule.next_crawl_at)}` : "按需同步"}`}</span></footer>
      </div>
    </div>
  );
}
