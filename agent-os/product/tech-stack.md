# Tech Stack

## Frontend

- React, Vite, TypeScript
- Tailwind, shadcn/ui
- TanStack Table, ותצוגת תמונה עם זום וסיבוב
- ממשק רב-לשוני: עברית (ברירת מחדל), אנגלית, ערבית ורוסית, עם החלפת RTL/LTR אוטומטית. בורר שפה בכותרת, והבחירה נשמרת בדפדפן. המחרוזות נמצאות ב-`frontend/src/i18n/locales/` (העברית היא המקור, והקומפיילר בודק שבכל שפה קיימים כל המפתחות). הוורוד (tertiary, #b80b60) שמור לסימון "לבדיקה" בלבד. עיצוב לפי פרויקט Stitch "MediScan RTL Excel Converter" (Heebo, טורקיז-נייבי).
- המסכים: Upload, Processing, Review, Export
- Phase 2: מסך התחברות, אזור אישי לכל תפקיד, ודשבורדים עם ספריית גרפים ל-React (מוצע: Recharts). הניווט והמסכים מוצגים לפי התפקיד.
- Phase 2ד: מסכים חדשים: ניהול משתמשים, חיפוש מטופלים, תיק מטופל וכללי ולידציה. עדכונים חיים מגיעים ב-EventSource (SSE), ודגימה נשארת כגיבוי.

## Backend

- Python 3.12, FastAPI, Pydantic
- עיבוד PDF ותמונה: PyMuPDF, Pillow (עמודים ב-200 DPI ותיקון סיבוב לפי EXIF)
- חילוץ: Claude API עם tool use לפלט JSON מובנה. מספר הקריאות המקבילות נקבע ב-`extract.concurrency`, וקריאה שנכשלה מנוסה שוב בהמתנה שגדלה בין ניסיון לניסיון.
- ייצוא: openpyxl
- צינור: כל שלב הוא מחלקה שמממשת `Stage(Protocol)` עם `run(form, ctx) -> FormDoc`, בקובץ משלה ב-`backend/pipeline/stages/`
- עיבוד ברקע. הממשק דוגם את הסטטוס כל שנייה.
- Phase 2: הרשאות כ-middleware או FastAPI dependency לפי תפקיד, כך שכל endpoint מצהיר אילו תפקידים מורשים. התחברות מקומית עם סיסמה מוצפנת (hash) וטוקן session.
- Phase 2: כל שינוי סטטוס וכל תיקון שדה עוברים דרך שירות אחד שכותב גם ל-`audit_log`. הדשבורדים נגזרים מ-`audit_log` ומטבלאות הרשומות.
- Phase 2ד (מהירות): כל עמוד הוא משימה אסינכרונית נפרדת, וכל העמודים יוצאים במקביל. ה-Semaphore משותף לכל המערכת ומתאים את עצמו ל-429 (`extract.adaptive`). אפשר לקבוע מודל לכל שלב (`models.*` ב-pipeline.yaml). Prompt caching על ההוראות והסכמה. הבדיקה הכפולה ומיקום השדות רצים ברקע אחרי שהעמוד כבר נשמר. endpoint של SSE לכל ערימה.
- Phase 2ד (כללים): Claude עם tool use ממיר כלל בעברית ל-JSON מובנה (תנאים ופעולה). מנוע הכללים דטרמיניסטי, בלי LLM בזמן הריצה, ורץ בשלב validate. "הרצה יבשה" על כל הטפסים הקיימים בשאילתה אחת.

## Database

- SQLite דרך SQLModel
- ישויות: Batch, SourceFile, Form, Field (ערך, ערך גולמי, ביטחון, רמה, סיבות, תוקן ידנית)
- Phase 2:
  - User (שם, תפקידים: intake / approver / lab_manager / admin, פעיל). מחיקה רכה בלבד
  - AuditLog (מי, מתי, סוג פעולה, ישות ומזהה, ערך לפני, ערך אחרי)
  - Phase 2ד: Patient הוא תצוגה מקובצת לפי ת.ז. מנורמלת (אינדקס על Field name='id_number'), בלי טבלה נפרדת. ValidationRule (טקסט מקורי, JSON מובנה, סטטוס: טיוטה / פעיל / מושבת, גרסה, נוצר ע"י, הופעל ע"י)
  - ב-Form: סטטוס זרימת עבודה (בעיבוד → ממתין לתיקון → ממתין לאישור → הוחזר → אושר), משויך ל-, הערת מאשר

## Other

- הרצה: Docker Compose (`docker compose up`)
- הגדרות מחוץ לקוד: `pipeline.yaml`, `senders.yaml`, `export.yaml`, `.env`
- בדיקות: pytest. מדידת דיוק: `python -m eval.run`
- פיתוח: Claude Code
- פרטיות: מפתח ה-API נשמר ב-.env, ותיקיית `data/` מוחרגת ב-git. הלוגים כוללים רק מזהים וסטטוסים, בלי ערכי שדות.
