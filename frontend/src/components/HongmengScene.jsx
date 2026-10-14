import { memo, useEffect, useRef, useState } from "react";
import { createAtmosphere } from "./hongmengAtmosphere.js";

const MOTES = Array.from({ length: 28 }, (_, index) => ({
  x: 39 + ((index * 37) % 59), y: 17 + ((index * 23) % 66),
  duration: 8 + (index % 5) * 2, delay: -(index * 1.7),
}));

function HongmengScene({ paused = false }) {
  const canvas = useRef(null);
  const controller = useRef(null);
  const [renderer, setRenderer] = useState("fallback");
  useEffect(() => {
    controller.current = createAtmosphere(canvas.current, setRenderer);
    const surface = canvas.current.closest(".mythic-hero");
    const move = event => {
      if (event.pointerType === "touch") return;
      const box = surface.getBoundingClientRect();
      if (box.width && box.height) controller.current?.setPointer((event.clientX - box.left) / box.width * 2 - 1, (event.clientY - box.top) / box.height * 2 - 1);
    };
    const leave = () => controller.current?.setPointer(0, 0);
    surface?.addEventListener("pointermove", move, { passive: true });
    surface?.addEventListener("pointerleave", leave);
    return () => {
      surface?.removeEventListener("pointermove", move);
      surface?.removeEventListener("pointerleave", leave);
      controller.current?.dispose(); controller.current = null;
    };
  }, []);
  useEffect(() => { controller.current?.setPaused(paused); }, [paused]);

  return <div className="celestial-art hongmeng-art" data-scene="hongmeng-cloud-sea" data-composition="boundless-confluence"
    data-renderer={renderer} data-paused={String(paused)} aria-hidden="true">
    <div className="hongmeng-fallback" />
    <canvas ref={canvas} data-layer="atmosphere" />
    <div className="hongmeng-aura" />
    <div className="hongmeng-vapour hongmeng-vapour-far" />
    <div className="hongmeng-vapour hongmeng-vapour-near" />
    <div className="hongmeng-motes">{MOTES.map((mote, index) => <i key={index} style={{
      "--mote-x": `${mote.x}%`, "--mote-y": `${mote.y}%`, "--mote-duration": `${mote.duration}s`, "--mote-delay": `${mote.delay}s`,
    }} />)}</div>
  </div>;
}
export default memo(HongmengScene);
