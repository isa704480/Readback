import { Swiper, SwiperSlide } from 'swiper/react';
import { A11y, Autoplay, Keyboard, Pagination } from 'swiper/modules';
import 'swiper/css';
import 'swiper/css/pagination';
import 'swiper/css/a11y';
import { SlotStrip, locked, settled } from '../components';
import { useI18n } from '../i18n';
import { FORMATS } from '../lib/formats';
import type { FormatDef } from '../lib/formats';
import { useMotionAllowed } from '../lib/motion-prefs';

/* One slide per format the solver arbitrates, each with a checksum-valid
 * example (lib/formats.ts, shared with the Formats reference), its check digit
 * locked, and who reads it aloud today. Slides size to their identifier -- an
 * IBAN is twice a container number and pretending otherwise would wrap it.
 *
 * Autoplay only when motion is allowed, and it stops for good the moment
 * someone touches the carousel: a slide that moves while it is being read is
 * the page taking the reader's attention away from them. */

function slotsOf(f: FormatDef) {
  return [...f.example].flatMap((ch, i) => (f.checkPos.includes(i) ? locked(ch) : settled(ch)));
}

export function FormatCarousel() {
  const { t } = useI18n();
  const moving = useMotionAllowed();

  return (
    <Swiper
      className="formats"
      modules={[A11y, Autoplay, Keyboard, Pagination]}
      slidesPerView="auto"
      spaceBetween={16}
      grabCursor
      keyboard={{ enabled: true }}
      pagination={{ clickable: true }}
      a11y={{ containerMessage: t('landing.formats.label') }}
      {...(moving
        ? { autoplay: { delay: 4500, disableOnInteraction: true, pauseOnMouseEnter: true } }
        : {})}
    >
      {FORMATS.map((f) => (
        <SwiperSlide key={f.id} className="formats__slide">
          <article className="format">
            <header className="format__head">
              <h3 className="format__name">{t(f.name)}</h3>
              <span className="format__length">{t(f.length)}</span>
            </header>
            <p className="format__label">{t('landing.formats.valid')}</p>
            <SlotStrip slots={slotsOf(f)} label={`${t(f.name)}: ${f.example}`} />
            <p className="format__check">{t(f.check)}</p>
            <p className="format__who">{t(f.who)}</p>
          </article>
        </SwiperSlide>
      ))}
    </Swiper>
  );
}
