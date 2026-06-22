import React from "react";

interface EditorCanvasProps {
  canvasRef: React.Ref<HTMLCanvasElement>;
  backgroundUrl: string | null;
  zoom: number;
}

function EditorCanvas({ canvasRef, backgroundUrl, zoom }: EditorCanvasProps) {
  return (
    <div className="flex flex-1 flex-col items-center justify-start overflow-auto bg-slate-300 p-6">
      {!backgroundUrl && (
        <p className="mb-4 rounded-xl border border-dashed border-slate-400 bg-slate-200 px-6 py-3 text-sm text-slate-500">
          Faça upload de uma imagem de fundo para começar a editar.
        </p>
      )}

      <div
        style={{
          transform: `scale(${zoom})`,
          transformOrigin: "top center",
          transition: "transform 0.15s ease",
        }}
      >
        <canvas
          ref={canvasRef}
          className="block shadow-2xl"
          style={{ cursor: "default" }}
        />
      </div>
    </div>
  );
}

export default EditorCanvas;
