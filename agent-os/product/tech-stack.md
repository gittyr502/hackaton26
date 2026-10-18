# Tech Stack

## Frontend

- React, Vite, TypeScript
- Tailwind, shadcn/ui
- TanStack Table, ותצוגת תמונה עם זום וסיבוב
- ממשק רב-לשוני: עברית (ברירת מחדל), אנגלית, ערבית ורוסית, עם החלפת RTL/LTR אוטומטית. בורר שפה בכותרת, והבחירה נשמרת בדפדפן. המחרוזות נמצאות ב-`frontend/src/i18n/locales/` (העברית היא המקור, והקומפיילר בודק שבכל שפה קיימים כל המפתחות). הוורוד (tertiary, #b80b60) שמור לסימון "לבדיקה" בלבד. עיצוב לפי פרויקט Stitch "MediScan RTL Excel Converter" (Heebo, טורקיז-נייבי).
- המסכים: Upload, Processing, Review, Export
- Phase 2: מסך התחברות, אזור אישי לכל תפקיד, ודשבורדים עם ספריית גרפים ל-React (מוצע: Recharts). הניווט והמסכים מוצגים לפי התפקיד.

## Backend

- Python 3.12, FastAPI, Pydantic
- עיבוד PDF ותמונה: PyMuPDF, Pillow (עמודים ב-200 DPI ותיקון סיבוב לפי EXIF)
- חילוץ: Claude API עם tool use לפלט JSON מובנה. מספר הקריאות המקבילות נקבע ב-`extract.concurrency`, וקריאה שנכשלה מנוסה שוב בהמתנה שגדלה בין ניסיון לניסיון.
- ייצוא: openpyxl
- צינור: כל שלב הוא מחלקה שמממשת `Stage(Protocol)` עם `run(form, ctx) -> FormDoc`, בקובץ משלה ב-`backend/pipeline/stages/`
- עיבוד ברקע. הממשק דוגם את הסטטוס כל שנייה.
- Phase 2: הרשאות כ-middleware או FastAPI dependency לפי תפקיד, כך שכל endpoint מצהיר אילו תפקידים מורשים. התחברות מקומית עם סיסמה מוצפנת (hash) וטוקן session.
- Phase 2: כל שינוי סטטוס וכל תיקון שדה עוברים דרך שירות אחד שכותב גם ל-`audit_log`. הדשבורדים נגזרים מ-`audit_log` ומטבלאות הרשומות.

## Database

- SQLite דרך SQLModel
- ישויות: Batch, SourceFile, Form, Field (ערך, ערך גולמי, ביטחון, רמה, סיבות, תוקן ידנית)
- Phase 2:
  - User (שם, תפקיד: intake / approver / lab_manager / admin, פעיל)
  - AuditLog (מי, מתי, סוג פעולה, ישות ומזהה, ערך לפני, ערך אחרי)
  - ב-Form: סטטוס זרימת עבודה (בעיבוד → ממתין לתיקון → ממתין לאישור → הוחזר → אושר), משויך ל-, הערת מאשר

## Other

- הרצה: Docker Compose (`docker compose up`)
- הגדרות מחוץ לקוד: `pipeline.yaml`, `senders.yaml`, `export.yaml`, `.env`
- בדיקות: pytest. מדידת דיוק: `python -m eval.run`
- פיתוח: Claude Code
- פרטיות: מפתח ה-API נשמר ב-.env, ותיקיית `data/` מוחרגת ב-git. הלוגים כוללים רק מזהים וסטטוסים, בלי ערכי שדות.
