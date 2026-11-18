(() => {
/* Mini-Icons für die Termine — eine Form je Kategorie.
 *
 * Gezeichnet als SVG und zur Laufzeit in die Karte geladen, statt als Sprite
 * mitgeliefert: so lassen sie sich beim Themenwechsel in der passenden Farbe
 * neu erzeugen, und es gibt keine zweite Datei, die zur Palette passen muss.
 *
 * Alles ist auf 24×24 gezeichnet und wird bei elf Bildpunkten angezeigt. Was
 * dort noch lesbar ist, hat höchstens drei Striche.
 */

const S = 24;

/* Jede Form: ein Pfad für Striche, optional einer für Flächen. */
const SHAPES = {
  musik: {                       // Achtelnote
    stroke: 'M9 16.5V5.5l8-2v11',
    fill: 'M6.6 19.4a2.4 2.4 0 1 0 4.8 0 2.4 2.4 0 1 0-4.8 0M14.6 17.4a2.4 2.4 0 1 0 4.8 0 2.4 2.4 0 1 0-4.8 0',
  },
  theater: {                     // Vorhang
    stroke: 'M4 5h16M5.5 5c0 7 2 11 6.5 14 4.5-3 6.5-7 6.5-14',
  },
  kunst: {                       // Pinsel
    stroke: 'M18 4.5 9.5 13M7 15.5c1.6-1.6 3.4-1.6 4.6-.4 1.2 1.2 1.2 3 -.4 4.6-1.2 1.2-4 1.6-6.2 1.3.4-2.2.8-4.3 2-5.5Z',
  },
  literatur: {                   // aufgeschlagenes Buch
    stroke: 'M12 7.5v12M12 7.5C10 5.8 7 5.3 4 5.6v12c3-.3 6 .2 8 1.9M12 7.5c2-1.7 5-2.2 8-1.9v12c-3-.3-6 .2-8 1.9',
  },
  film: {                        // Filmstreifen
    stroke: 'M4 6h16v12H4zM4 10h16M4 14h16M8 6v12M16 6v12',
  },
  kinder: {                      // Drachen an der Schnur
    stroke: 'M12 3.5 19 10l-7 6.5L5 10zM12 16.5v4M12 20.5c-1.6 0-1.6-1.6-3-1.6',
  },
  museum: {                      // Giebel auf Säulen
    stroke: 'M3 9.5 12 4.5l9 5M5.5 9.5v8M10 9.5v8M14 9.5v8M18.5 9.5v8M3.5 19.5h17',
  },
  'markt/fest': {                // Wimpel
    stroke: 'M6 4v17M6 5.5h12l-3 3.5 3 3.5H6',
  },
  sport: {                       // Ball mit Naht
    stroke: 'M12 3.8a8.2 8.2 0 1 0 0 16.4 8.2 8.2 0 1 0 0-16.4M5 8.5c4 1.6 10 1.6 14 0M5 15.5c4-1.6 10-1.6 14 0',
  },
  vortrag: {                     // Sprechblase
    stroke: 'M4.5 6h15v10h-8l-4.5 4v-4h-2.5zM8.5 11h7',
  },
  comedy: {                      // lachender Mund
    stroke: 'M12 3.8a8.2 8.2 0 1 0 0 16.4 8.2 8.2 0 1 0 0-16.4M7.5 13c1 3 8 3 9 0M9 9.5v.5M15 9.5v.5',
  },
  party: {                       // Discokugel
    stroke: 'M12 3v3M12 6a7 7 0 1 0 0 14 7 7 0 1 0 0-14M5.5 11h13M5.5 15h13M12 6c-3 4-3 10 0 14M12 6c3 4 3 10 0 14',
  },
  kulinarik: {                   // Weinglas
    stroke: 'M7 4h10c0 5-1.5 8-5 8s-5-3-5-8ZM12 12v7.5M8.5 19.5h7',
  },
  draussen: {                    // zwei Gipfel
    stroke: 'M3 19 9.5 7l4 7 2.5-4L21 19Z',
  },
  kurs: {                        // Schere
    stroke: 'M6.5 6.5a2 2 0 1 0 0 .1M6.5 17.5a2 2 0 1 0 0 .1M8.3 8 19 17M8.3 16 19 7',
  },
  gemeinde: {                    // Rathaus mit Turm
    stroke: 'M4 20V10h16v10M3 20h18M10 10V6l2-2.5L14 6v4M8 14v3M12 14v3M16 14v3',
  },
  sonstiges: {                   // Raute
    stroke: 'M12 5.5 18.5 12 12 18.5 5.5 12Z',
  },
};

function svg(shape, color) {
  const parts = [];
  if (shape.stroke) {
    parts.push(`<path d="${shape.stroke}" fill="none" stroke="${color}" `
      + `stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"/>`);
  }
  if (shape.fill) parts.push(`<path d="${shape.fill}" fill="${color}"/>`);
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${S} ${S}" `
    + `width="${S * 2}" height="${S * 2}">${parts.join('')}</svg>`;
}

async function raster(markup) {
  // Data-URL statt Blob und `createImageBitmap`: Letzteres lehnt SVG je nach
  // Browser ab („The source image could not be decoded"). Ein <img> auf eine
  // Data-URL und eine Zeichenfläche tun es überall.
  const url = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(markup)}`;
  const img = new Image(S * 2, S * 2);
  await new Promise((resolve, reject) => {
    img.onload = resolve;
    img.onerror = () => reject(new Error('SVG nicht lesbar'));
    img.src = url;
  });
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = S * 2;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  ctx.drawImage(img, 0, 0, S * 2, S * 2);
  return ctx.getImageData(0, 0, S * 2, S * 2);
}

/** Lädt für jede Kategorie ein Bild `cat-<name>` in die Karte. */
async function installIcons(map, color) {
  await Promise.all(Object.entries(SHAPES).map(async ([name, shape]) => {
    const id = `cat-${name}`;
    const image = await raster(svg(shape, color));
    if (map.hasImage(id)) map.removeImage(id);
    map.addImage(id, image, { pixelRatio: 2 });
  }));
}

window.installIcons = installIcons;
})();
