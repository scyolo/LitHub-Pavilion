import { useEffect, useRef, useState } from "react";
import Icon from "./Icon.jsx";

export default function SearchInput({ value = "", onCommit, label = "搜索论文", placeholder, automatic = true, autoFocus = false }) {
  const [draft, setDraft] = useState(value);
  const timer = useRef(null);
  const composing = useRef(false);
  const commit = useRef(onCommit);
  commit.current = onCommit;

  useEffect(() => {
    clearTimeout(timer.current);
    setDraft(value);
  }, [value]);
  useEffect(() => () => clearTimeout(timer.current), []);

  function submit(next) {
    clearTimeout(timer.current);
    commit.current(next.trim());
  }

  return (
    <form className="search-input" role="search" onSubmit={(event) => { event.preventDefault(); if (!composing.current) submit(draft); }}>
      <Icon name="search" size={19} />
      <input aria-label={label} value={draft} maxLength={300} autoFocus={autoFocus} type="search"
        placeholder={placeholder || "搜索英文标题、摘要关键词…"}
        onCompositionStart={() => { composing.current = true; clearTimeout(timer.current); }}
        onCompositionEnd={(event) => { composing.current = false; if (automatic) submit(event.currentTarget.value); }}
        onChange={(event) => {
          const next = event.target.value;
          setDraft(next);
          clearTimeout(timer.current);
          if (automatic && !composing.current) timer.current = setTimeout(() => commit.current(next.trim()), 450);
        }} />
      {draft ? <button className="icon-button" type="button" aria-label="清空搜索" onClick={() => { setDraft(""); submit(""); }}><Icon name="close" size={15} /></button>
        : <kbd aria-hidden="true">↵</kbd>}
    </form>
  );
}
