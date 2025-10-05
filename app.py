%%writefile app.py
import streamlit as st
from Bio import Entrez
from datetime import datetime, timedelta
import time
import http.client
import pandas as pd

MAX_TOTAL_ARTICLES = 10000
MAX_PER_KEYWORD = 9500

def safe_read(handle):
    try:
        return Entrez.read(handle)
    except http.client.IncompleteRead as e:
        return Entrez.read(e.partial)

def is_ukrainian_affiliation(affil_text):
    affil_lower = affil_text.lower()
    return any(word in affil_lower for word in [
        "ukraine", "ukrainian", "україна", "україни", "україні"
    ])

def has_joint_publications(author_name, target_author, email):
    Entrez.email = email
    query = f"{author_name}[Author] AND {target_author}[Author]"
    try:
        handle = Entrez.esearch(db="pubmed", term=query, retmax=0)
        record = Entrez.read(handle)
        handle.close()
        return int(record["Count"]) > 0
    except:
        return False

def count_author_articles(author_name, email):
    Entrez.email = email
    today = datetime.now()
    five_years_ago = today - timedelta(days=5 * 365)
    date_range = f"{five_years_ago.strftime('%Y/%m/%d')}[PDat] : {today.strftime('%Y/%m/%d')}[PDat]"
    query = f"{author_name}[Author] AND {date_range}"
    try:
        handle = Entrez.esearch(db="pubmed", term=query, retmax=0)
        record = Entrez.read(handle)
        handle.close()
        return int(record["Count"])
    except:
        return 0

def summarize_final_candidates(author_dict, target_author, email):
    final = []
    for key, data in author_dict.items():
        name = data["name"]
        affil = data["affil"]
        orcid = data["orcid"]
        keywords = sorted(set(data["keywords"]))
        if has_joint_publications(name, target_author, email):
            continue
        count = count_author_articles(name, email)
        final.append({
            "Автор": name,
            "Афіліація": affil,
            "ORCID": orcid,
            "Статей за 5 років": count,
            "Ключові слова": ", ".join(keywords)
        })
    df = pd.DataFrame(final)
    df = df.sort_values(by="Статей за 5 років", ascending=False)
    return df

def get_keyword_counts(keywords, email, date_range):
    Entrez.email = email
    Entrez.tool = "UkrainianReviewerFinder"
    keyword_counts = {}
    for kw in set(keywords):
        handle = Entrez.esearch(db="pubmed", term=f"{kw}[All Fields] AND {date_range}", retmax=0)
        record = Entrez.read(handle)
        handle.close()
        count = int(record["Count"])
        keyword_counts[kw] = count
    return keyword_counts

def search_pubmed_articles(email, author_lastname, affiliation):
    Entrez.email = email
    Entrez.tool = "UkrainianReviewerFinder"

    today = datetime.now()
    five_years_ago = today - timedelta(days=5 * 365)
    date_range = f"{five_years_ago.strftime('%Y/%m/%d')}[PDat] : {today.strftime('%Y/%m/%d')}[PDat]"
    query = f"{author_lastname}[Author] AND {affiliation}[Affiliation] AND {date_range}"

    handle = Entrez.esearch(db="pubmed", term=query, retmax=1000)
    record = Entrez.read(handle)
    handle.close()
    id_list = record["IdList"]

    keywords = []
    batch_size = 20
    for i in range(0, len(id_list), batch_size):
        batch_ids = id_list[i:i+batch_size]
        time.sleep(0.5)
        try:
            fetch_handle = Entrez.efetch(db="pubmed", id=batch_ids, rettype="medline", retmode="text")
            article_data = fetch_handle.read()
            fetch_handle.close()
        except Exception as e:
            st.error(f"❌ Помилка при отриманні даних для batch {i}: {e}")
            continue

        for line in article_data.split("\n"):
            if line.startswith("OT  -"):
                keyword = line.replace("OT  - ", "").strip()
                keywords.append(keyword)

    return keywords, len(id_list)

def find_authors_by_keywords(keywords, email, target_author):
    Entrez.email = email
    Entrez.tool = "UkrainianReviewerFinder"

    today = datetime.now()
    five_years_ago = today - timedelta(days=5 * 365)
    date_range = f"{five_years_ago.strftime('%Y/%m/%d')}[PDat] : {today.strftime('%Y/%m/%d')}[PDat]"

    keyword_counts = get_keyword_counts(keywords, email, date_range)
    sorted_keywords = sorted(keyword_counts.items(), key=lambda x: x[1])

    author_dict = {}
    total_articles_processed = 0

    for keyword, count in sorted_keywords:
        if total_articles_processed + min(count, MAX_PER_KEYWORD) > MAX_TOTAL_ARTICLES:
            st.warning(f"⏸️ Пауза перед ключовим словом **{keyword}**, щоб не перевищити ліміт 10 000 статей.")
            ukrainian_authors = {
                k: v for k, v in author_dict.items() if is_ukrainian_affiliation(v["affil"])
            }
            df = summarize_final_candidates(ukrainian_authors, target_author, email)
            st.success(f"✅ Українських авторів без спільних публікацій: {len(df)}")
            st.dataframe(df.reset_index(drop=True), use_container_width=True)
            total_articles_processed = 0
            time.sleep(5)

        max_to_process = min(count, MAX_PER_KEYWORD)
        st.markdown(f"### 🔍 Ключове слово: **{keyword}** — `{count}` статей (обробляємо до {max_to_process})")
        query = f"{keyword}[All Fields] AND {date_range}"
        handle = Entrez.esearch(db="pubmed", term=query, usehistory="y", retmax=0)
        record = Entrez.read(handle)
        handle.close()
        webenv = record["WebEnv"]
        query_key = record["QueryKey"]
        batch_size = 50
        retrieved = 0

        while retrieved < max_to_process:
            time.sleep(0.5)
            try:
                fetch_handle = Entrez.efetch(
                    db="pubmed",
                    rettype="xml",
                    retmode="xml",
                    retstart=retrieved,
                    retmax=batch_size,
                    query_key=query_key,
                    webenv=webenv
                )
                records = safe_read(fetch_handle)
                fetch_handle.close()
            except Exception as e:
                st.error(f"❌ Помилка при отриманні batch {retrieved}: {e}")
                break

            if "PubmedArticle" not in records:
                break
            for article in records["PubmedArticle"]:
                pub_date = article["MedlineCitation"].get("DateCompleted", {})
                year = int(pub_date.get("Year", 1900))
                month = int(pub_date.get("Month", 1))
                day = int(pub_date.get("Day", 1))
                article_date = datetime(year, month, day)

                if "AuthorList" not in article["MedlineCitation"]["Article"]:
                    continue
                for author in article["MedlineCitation"]["Article"]["AuthorList"]:
                    name = ""
                    if "LastName" in author and "Initials" in author:
                        name = f"{author['LastName']} {author['Initials']}"
                    elif "CollectiveName" in author:
                        name = author["CollectiveName"]
                    affil = ""
                    if "AffiliationInfo" in author:
                        affil_blocks = author["AffiliationInfo"]
                        if affil_blocks and "Affiliation" in affil_blocks[0]:
                            affil = affil_blocks[0]["Affiliation"]
                    orcid = ""
                    if "Identifier" in author:
                        for ident in author["Identifier"]:
                            if ident.attributes.get("Source") == "ORCID":
                                orcid = str(ident)
                    key = orcid if orcid else name
                    if key not in author_dict or article_date > author_dict[key]["latest_date"]:
                        author_dict[key] = {
                            "name": name,
                            "affil": affil,
                            "orcid": orcid,
                            "latest_date": article_date,
                            "keywords": []
                        }
                    author_dict[key]["keywords"].append(keyword)
            retrieved += batch_size
            total_articles_processed += batch_size

    return author_dict
# 🎨 Streamlit UI
st.set_page_config(page_title="PubMed Аналізатор", layout="centered")
st.title("🔬 Пошук ключових слів та українських рецензентів")
st.markdown("Крок 1: знайти ключові слова автора. Крок 2: знайти авторів статей з тими ж ключовими словами. Крок 3: вибрати українських рецензентів без спільних публікацій.")

email = st.text_input("📧 Ваш email для доступу до PubMed")
lastname = st.text_input("👤 Прізвище автора")
affiliation = st.text_input("🏢 Афіліація автора")

if "keywords" not in st.session_state:
    st.session_state.keywords = []
if "author_dict" not in st.session_state:
    st.session_state.author_dict = {}

# КРОК 1: Пошук ключових слів
if st.button("🔍 Крок 1: Знайти ключові слова автора"):
    if not email or not lastname or not affiliation:
        st.warning("Будь ласка, заповніть email, прізвище та афіліацію автора.")
    else:
        with st.spinner("Пошук ключових слів..."):
            keywords, count = search_pubmed_articles(email, lastname, affiliation)
            st.session_state.keywords = keywords
            st.session_state.search_attempted = True  # 🔑 позначає, що пошук був

        st.success(f"✅ Знайдено {count} статей.")

# 🔑 Вивід ключових слів, якщо знайдено
if st.session_state.get("keywords"):
    st.subheader("🔑 Ключові слова:")
    for kw in sorted(set(st.session_state.keywords)):
        st.markdown(f"- {kw}")

# ✍️ Пропозиція ручного введення — тільки якщо пошук був і ключові слова не знайдено
elif st.session_state.get("search_attempted") and not st.session_state.keywords:
    st.warning("❌ Ключові слова не знайдено. Ви можете ввести їх вручну нижче.")
    manual_input = st.text_input("✍️ Введіть ключові слова вручну (через крапку з комою):")
    if manual_input:
        manual_keywords = [kw.strip() for kw in manual_input.split(";") if kw.strip()]
        st.session_state.keywords = manual_keywords
        st.success(f"✅ Введено {len(manual_keywords)} ключових слів вручну.")
        st.subheader("🔑 Ключові слова:")
        for kw in manual_keywords:
            st.markdown(f"- {kw}")

# КРОК 2: Пошук авторів
if st.button("🔎 Крок 2: Знайти авторів за ключовими словами"):
    if not st.session_state.keywords or not email or not lastname:
        st.warning("Будь ласка, заповніть email, прізвище автора та виконайте крок 1.")
    else:
        with st.spinner("Пошук авторів..."):
            author_dict = find_authors_by_keywords(st.session_state.keywords, email, lastname)
            st.session_state.author_dict = author_dict
        st.success(f"✅ Загалом знайдено {len(author_dict)} унікальних авторів.")

# КРОК 3: Вивід фінальної таблиці
if st.button("🇺🇦 Крок 3: Показати фінальну таблицю українських рецензентів"):
    if not st.session_state.author_dict or not email or not lastname:
        st.warning("Спочатку виконайте крок 2.")
    else:
        ukrainian_authors = {
            k: v for k, v in st.session_state.author_dict.items() if is_ukrainian_affiliation(v["affil"])
        }
        df = summarize_final_candidates(ukrainian_authors, lastname, email)
        st.success(f"✅ Українських авторів без спільних публікацій: {len(df)}")
        st.dataframe(df.reset_index(drop=True), use_container_width=True)

        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Завантажити таблицю в CSV",
            data=csv,
            file_name="ukrainian_reviewers.csv",
            mime="text/csv"
        )

# 🧩 КРОК 4: Пошук потенційних опонентів для дисертанта
st.markdown("---")
st.header("🧩 Крок 4: Пошук потенційних опонентів для дисертанта")

uploaded_file = st.file_uploader("📄 Завантажте CSV-файл з кандидатами", type="csv")

with st.expander("👥 Введіть дані 4 вчених"):
    col1, col2 = st.columns(2)
    head_name = col1.text_input("👤 Прізвище голови ради")
    head_affil = col2.text_input("🏢 Афіліація голови ради")

    supervisor_name = col1.text_input("👤 Прізвище керівника")
    supervisor_affil = col2.text_input("🏢 Афіліація керівника")

    reviewer1_name = col1.text_input("👤 Прізвище рецензента 1")
    reviewer1_affil = col2.text_input("🏢 Афіліація рецензента 1")

    reviewer2_name = col1.text_input("👤 Прізвище рецензента 2")
    reviewer2_affil = col2.text_input("🏢 Афіліація рецензента 2")

if st.button("🔍 Знайти опонентів"):
    if not uploaded_file:
        st.warning("Будь ласка, завантажте CSV-файл з кандидатами.")
    elif not lastname or not email:
        st.warning("Спочатку заповніть email та прізвище автора на Кроці 1.")
    else:
        df = pd.read_csv(uploaded_file)
        st.info(f"📊 Завантажено {len(df)} кандидатів.")

        exclude_names = [lastname, head_name, supervisor_name, reviewer1_name, reviewer2_name]
        exclude_names = [name for name in exclude_names if name]

        filtered_rows = []
        with st.spinner("🔎 Перевірка спільних публікацій..."):
            for _, row in df.iterrows():
                candidate_name = row["Автор"]
                if any(has_joint_publications(candidate_name, other, email) for other in exclude_names):
                    continue
                filtered_rows.append(row)

        if filtered_rows:
            result_df = pd.DataFrame(filtered_rows)
            st.success(f"✅ Знайдено {len(result_df)} потенційних опонентів.")
            st.dataframe(result_df.reset_index(drop=True), use_container_width=True)

            csv = result_df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Завантажити таблицю опонентів в CSV",
                data=csv,
                file_name="potential_opponents.csv",
                mime="text/csv"
            )
        else:
            st.warning("❌ Не знайдено жодного кандидата без спільних публікацій.")