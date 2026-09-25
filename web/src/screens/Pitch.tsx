import type { ReactNode } from 'react';
import { ButtonLink, NAV_PATHS } from '../components';
import './Pitch.css';

/* Pitch Day 3.0 -- 1-bosqich (12-sentabr -- 11-oktabr).
 *
 * Musobaqa talab qilgan olti bo'lim, bir sahifada. O'zbek-first, chunki
 * hakamlar shu tilda o'qishadi. Landing sahifasi mahsulotning marketing yuzi;
 * bu sahifa esa g'oyani, jamoani, yo'l xaritasini va rejani ochib beradi.
 *
 * Har bir raqam docs/ dagi manbaga tayanadi; bir ham ixtiro qilingan
 * ma'lumot yo'q. Video/GitHub URL tayyor bo'lganda yuqoridagi ikki qatorni
 * o'zgartiring, boshqa hech nima. */

// Yangi video/havola bo'lganda shu ikki qatorni tahrirlang.
const DEMO_VIDEO_URL: string | null = null;
const GITHUB_URL: string = 'https://github.com/';

function Section({
  eyebrow,
  title,
  children,
}: {
  eyebrow: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="pitch__section">
      <p className="pitch__eyebrow">{eyebrow}</p>
      <h2 className="pitch__h2">{title}</h2>
      <div className="pitch__body">{children}</div>
    </section>
  );
}

function Stage({
  n,
  label,
  when,
  state,
  children,
}: {
  n: string;
  label: string;
  when: string;
  state: 'done' | 'now' | 'next';
  children: ReactNode;
}) {
  return (
    <li className={`stage stage--${state}`}>
      <span className="stage__mark" aria-hidden="true">
        {state === 'done' ? '✓' : state === 'now' ? '●' : n}
      </span>
      <div>
        <h3 className="stage__head">
          {label}
          <span className="stage__when">{when}</span>
        </h3>
        <p className="stage__body">{children}</p>
      </div>
    </li>
  );
}

export function Pitch() {
  return (
    <article className="pitch">
      <header className="pitch__hero">
        <p className="pitch__kicker">Pitch Day 3.0 &middot; 1-bosqich</p>
        <h1 className="pitch__title">
          Readback &mdash; telefonda o&lsquo;qilgan raqamlarni <em>to&lsquo;g&lsquo;ri</em> yozib
          oladigan ovozli AI agent.
        </h1>
        <p className="pitch__lede">
          Har bir chaqiruv markazi, sug&lsquo;urta va logistika kompaniyasi bir kunda o&lsquo;nlab
          marta <q>Yana bir marta ayting</q> deb so&lsquo;raydi. Readback bu yo&lsquo;qotilgan
          vaqtni tozalaydi: shovqinda ham u raqamning to&lsquo;g&lsquo;riligini qanday
          tekshirishni biladi.
        </p>
        <div className="pitch__cta">
          <ButtonLink to={NAV_PATHS.demo} variant="primary">
            Prototipni sinash
          </ButtonLink>
          <ButtonLink to="/" variant="secondary">
            Mahsulot sahifasi
          </ButtonLink>
        </div>
      </header>

      <Section eyebrow="01" title="Muammo va yechim">
        <div className="grid-2">
          <div>
            <h3 className="pitch__h3">Muammo</h3>
            <p>
              Chaqiruv markazlari, logistika va bank operatorlari har kuni telefon orqali raqam
              yozib oladi &mdash; konteyner, IBAN, VIN, bemor kodi, karta. Shovqinda <b>5 va 9</b>,
              <b> M va N</b>, <b>S va F</b> bir xil eshitiladi. Bitta noto&lsquo;g&lsquo;ri belgi
              &mdash; konteyner boshqa portga jo&lsquo;natiladi, to&lsquo;lov qaytariladi yoki dori
              boshqa odamga beriladi.
            </p>
            <p>
              Odamlar bunga <q>Bravo uchun B mi, Delta uchun D mi?</q> deb har bir belgini qaytadan
              so&lsquo;rash bilan javob berishadi. Bir raqamga 15&ndash;20 soniya sarflanadi,
              mijoz asablanadi, operatorning kunlik unumdorligi 30% pasayadi.
            </p>
          </div>
          <div>
            <h3 className="pitch__h3">Yechim</h3>
            <p>
              Readback fonda tinglaydi va raqamning <b>qanday bo&lsquo;lishi kerakligini biladi</b>.
              Konteyner raqami ISO 6346 nazorat raqamiga bo&lsquo;ysunadi, IBAN mod-97 ni beradi,
              karta Luhn&lsquo;ni. Bu cheklov mikrofonni yaxshilamaydi &mdash; u tizim
              ko&lsquo;tara oladigan xato darajasini <b>15 barobar oshiradi</b>.
            </p>
            <p>
              Uchdan ikki holatda noto&lsquo;g&lsquo;ri eshitilganini o&lsquo;zi jimgina tuzatadi
              va ekranda farqni ko&lsquo;rsatadi. Tuzata olmasa &mdash; bir marta, bitta belgi
              haqida so&lsquo;raydi va yana jim bo&lsquo;ladi. Transkript saqlanmaydi. Qaytadigani
              &mdash; raqam va necha marta gap bo&lsquo;linganining hisobi.
            </p>
          </div>
        </div>
      </Section>

      <Section eyebrow="02" title="Jamoa">
        <div className="team">
          <div className="team__card">
            <p className="team__name">Islombek Fayzullaev</p>
            <p className="team__role">Solo full-stack va AI muhandisi</p>
            <ul className="team__list">
              <li>
                <b>Python</b>, FastAPI, SQLAlchemy, PostgreSQL &mdash; server, sessiya boshqaruvi,
                audit jurnali
              </li>
              <li>
                <b>TypeScript</b>, React, Vite &mdash; web ilova, jonli mikrofon oqimi
                (AudioWorklet {'->'} PCM16 {'->'} WebSocket)
              </li>
              <li>
                <b>Ovoz AI</b>: AssemblyAI Universal-3.5 Pro Streaming, tur boshqaruvi, keyterm
                biasing, LLM Gateway
              </li>
              <li>
                <b>Vizual</b>: Three.js, Motion, Chart.js, Swiper &mdash; landing sahifasidagi 3D
                sahna va grafik
              </li>
              <li>
                <b>Infratuzilma</b>: Render, Vercel, GitHub Actions (keep-alive), Neon Postgres
              </li>
            </ul>
            <p className="team__contact">
              <a href="mailto:info@fayzinc.com">info@fayzinc.com</a>
              {' · '}
              <a href={GITHUB_URL} target="_blank" rel="noreferrer">
                GitHub
              </a>
            </p>
          </div>
          <p className="team__note">
            Loyiha yakka o&lsquo;zim tomonidan qurilgan &mdash; 24 kun ichida 30+ commit, 180 test,
            uch tilli interfeys, admin paneli, audit jurnali va deploy. Bu Pitch Day muddatida MVP
            dan keyingi bosqichga o&lsquo;tishga tayyor jamoa demakdir.
          </p>
        </div>
      </Section>

      <Section eyebrow="03" title="Nima uchun biz bu muammoni hal qila olamiz">
        <ul className="reasons">
          <li>
            <h3 className="pitch__h3">Cheklovni birinchi bo&lsquo;lib qo&lsquo;lladik</h3>
            <p>
              Boshqa ovozli agentlar <q>modelni yaxshilash</q> yo&lsquo;lidan boradi. Biz format
              cheklovini asos qilib oldik va uni 12 million simulyatsiya qilingan qamrov
              bo&lsquo;yicha 8 xil aksentda o&lsquo;lchadik. Cheklovsiz xato budjeti 0.0047,
              cheklov bilan 0.0692 &mdash; 14.9x. Bu docs/EXPERIMENT.md da yozilgan va o&lsquo;lchov
              skripti bilan takrorlanadi.
            </p>
          </li>
          <li>
            <h3 className="pitch__h3">Halol muhandislik amaliyoti</h3>
            <p>
              180 avtomatik test, xavfsizlik auditi (6 defekt yopilgan), immutable audit jurnali,
              tashkilotlar orasidagi ma&lsquo;lumot izolyatsiyasi. Har bir da&lsquo;vo
              o&lsquo;lchangan va uning manbai docs/ da ko&lsquo;rsatilgan. Yolg&lsquo;onchi{' '}
              <q>100%</q> raqamlari yo&lsquo;q.
            </p>
          </li>
          <li>
            <h3 className="pitch__h3">O&lsquo;zbek bozorini bilamiz</h3>
            <p>
              O&lsquo;zbekistonda logistika (temir yo&lsquo;l konteynerlari, avtokorxonalar),
              sug&lsquo;urta va bank chaqiruv markazlari &mdash; bularning hammasi raqam
              o&lsquo;qilishiga tayanadi. Interfeys o&lsquo;zbek, rus va inglizcha; telefonda
              ingliz tilida ishlaydi (AssemblyAI streaming O&lsquo;zbek tilini hozircha
              qo&lsquo;llamaydi va biz buni oshkora aytamiz).
            </p>
          </li>
        </ul>
      </Section>

      <Section eyebrow="04" title="Yo'l xaritasi">
        <ol className="stages">
          <Stage n="1" label="G'oya" when="31-avgust 2026" state="done">
            AssemblyAI Voice Agent Hackathon uchun tug&lsquo;ilgan g&lsquo;oya. Muammo aniq:
            shovqinda raqam noto&lsquo;g&lsquo;ri eshitiladi. Yechim: format o&lsquo;zining nazorat
            raqamini beradi.
          </Stage>
          <Stage n="2" label="Prototip" when="1-10 sentabr 2026" state="done">
            Solver (validator + posterior), replay yo&lsquo;li, ARM/IDLE detektori, 8 ta yozib
            olingan fixture. Hech qanday mikrofon yo&lsquo;q, faqat kod ustidagi arifmetika. 156
            test.
          </Stage>
          <Stage n="3" label="MVP" when="11-24 sentabr 2026" state="now">
            Jonli AssemblyAI soketi, browserdagi mikrofon yo&lsquo;li, ko&lsquo;p tashkilotli admin
            panel, audit jurnali, xavfsizlik auditi, uch tilli interfeys. 180 test. Hozir deploy
            bosqichida.
          </Stage>
          <Stage n="4" label="Ishga tushirish" when="Oktabr 2026" state="next">
            Uch pilot mijoz bilan haqiqiy chaqiruvlar (logistika, sug&lsquo;urta, bank),
            o&lsquo;lchangan sukunat va aniqlik ko&lsquo;rsatkichlari. AssemblyAI hakatonining
            top-5 va Pitch Day 2 va 3-bosqichlariga o&lsquo;tish.
          </Stage>
        </ol>
      </Section>

      <Section eyebrow="05" title="Yechimni qanday amalga oshiramiz">
        <div className="plan">
          <div>
            <h3 className="pitch__h3">Texnologik stak</h3>
            <ul>
              <li>
                <b>Ovoz</b>: AssemblyAI Universal-3.5 Pro Streaming (WebSocket), keyterm biasing,{' '}
                <code>UpdateConfiguration</code> orqali ARMED bo&lsquo;lganda cheklov
                ro&lsquo;yxatini yangilash, <code>ForceEndpoint</code> raqam tugagach sukunatni
                qaytarish
              </li>
              <li>
                <b>Server</b>: FastAPI + uvicorn, SQLAlchemy 2, PostgreSQL. Har bir sessiya bitta
                jarayon, bitta soket, ARCH 3.11 bo&lsquo;yicha kunlik byudjet
              </li>
              <li>
                <b>Web</b>: React 19, Vite, TypeScript, i18n uchburchak (en/uz/ru). AudioWorklet
                mikrofonni oladi va serverga PCM16 chunk sifatida yuboradi
              </li>
              <li>
                <b>Xavfsizlik</b>: pbkdf2_sha256 600k iteratsiya, kunlik va IP bo&lsquo;yicha rate
                limit, HttpOnly cookie, katalog per tashkilot, immutable audit jurnali
              </li>
            </ul>
          </div>
          <div>
            <h3 className="pitch__h3">Bosqichlar</h3>
            <ol>
              <li>
                <b>Sentabr</b>: MVP deploy, Pitch Day 3.0 topshirish, AssemblyAI hakaton
                topshirish
              </li>
              <li>
                <b>Oktabr</b>: Uch pilot mijoz bilan yopiq beta. Har bir chaqiruv uchun sukunat
                ulushi va so&lsquo;ralgan savollar sonini o&lsquo;lchash. LLM Gateway ni ikkinchi
                signal sifatida ulash
              </li>
              <li>
                <b>Noyabr-Dekabr</b>: Ochiq beta. To&lsquo;lov integratsiyasi, foydalanuvchi
                hisobi, sekundlik hisoblash bo&lsquo;yicha modeli
              </li>
              <li>
                <b>2027 Yanvar</b>: Kommersial ishga tushirish, birinchi to&lsquo;lovchi mijozlar
              </li>
            </ol>
          </div>
          <div>
            <h3 className="pitch__h3">AI vositalar</h3>
            <ul>
              <li>
                <b>AssemblyAI Universal-3.5 Pro</b> &mdash; real vaqtda tanib olish
              </li>
              <li>
                <b>AssemblyAI LLM Gateway</b> &mdash; format aniqlashda ikkinchi signal
              </li>
              <li>
                <b>Claude Code</b> &mdash; rejalashtirish va kod yozish yordamchisi
              </li>
              <li>
                <b>O&lsquo;z solverimiz</b> &mdash; nazorat raqami arifmetikasi va posterior.
                Chegaralar docs/EXPERIMENT.md da o&lsquo;lchangan
              </li>
            </ul>
          </div>
        </div>
      </Section>

      <Section eyebrow="06" title="Demo va prototip">
        <div className="demo-block">
          {DEMO_VIDEO_URL ? (
            <div className="demo-block__video">
              <iframe
                src={DEMO_VIDEO_URL}
                title="Readback demo videosi"
                allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                allowFullScreen
              />
            </div>
          ) : (
            <div className="demo-block__placeholder">
              <p>
                <b>Demo videosi tayyorlanmoqda.</b> 11-oktabrgacha bu joyga 1&ndash;5 daqiqalik
                video joylanadi.
              </p>
            </div>
          )}

          <div>
            <h3 className="pitch__h3">Video haqida</h3>
            <p>
              Videoda haqiqiy telefon suhbati taqlid qilinadi: operator konteyner raqamini
              so&lsquo;raydi, mijoz shovqinli aloqada aytadi. Ekranda Readback raqamni belgi-belgi
              to&lsquo;ldiradi, bittasini jimgina tuzatadi va farqni ko&lsquo;rsatadi. Ikkinchi
              qismda uni tuzata olmaydigan holat: bir marta so&lsquo;raydi va yozib oladi. Oxirida
              &mdash; sukunat foizi va bir kunlik pul tejash hisobi.
            </p>

            <h3 className="pitch__h3">Ishlaydigan prototip</h3>
            <ul className="demo-block__links">
              <li>
                <span>
                  <b>/demo</b> &mdash; 8 ta yozib olingan fixture, hisobsiz ishlaydi
                </span>
                <ButtonLink to={NAV_PATHS.demo} variant="secondary">
                  Ochish
                </ButtonLink>
              </li>
              <li>
                <span>
                  <b>/live</b> &mdash; jonli mikrofon (ro&lsquo;yxatdan o&lsquo;tish talab qiladi)
                </span>
                <ButtonLink to={NAV_PATHS.live} variant="secondary">
                  Ochish
                </ButtonLink>
              </li>
              <li>
                <span>
                  <b>/formats</b> &mdash; qo&lsquo;llab-quvvatlanadigan 5 format
                </span>
                <ButtonLink to={NAV_PATHS.formats} variant="secondary">
                  Ochish
                </ButtonLink>
              </li>
            </ul>

            <h3 className="pitch__h3">Manba kodi</h3>
            <p>
              To&lsquo;liq kod{' '}
              <a href={GITHUB_URL} target="_blank" rel="noreferrer">
                GitHub
              </a>{' '}
              da ochiq. Server (FastAPI, ~4000 qator), web (React, ~5000 qator), 180 avtomatik test
              va docs/ &mdash; hammasi bir repositoriyada.
            </p>
          </div>
        </div>
      </Section>

      <footer className="pitch__footer">
        <p>
          Savol yoki qo&lsquo;shimcha ma&lsquo;lumot uchun:{' '}
          <a href="mailto:info@fayzinc.com">info@fayzinc.com</a>
        </p>
      </footer>
    </article>
  );
}
