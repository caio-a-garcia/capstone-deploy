from flask import Flask, render_template, request, redirect, url_for, session, send_file
import pandas as pd
import os
import secrets
from jinja2 import Environment, select_autoescape
# Model dependencies
import pulp as pp
import math
import re
# Analysis dependencies
from collections import Counter
from pprint import pprint


app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = "uploads/"
app.config["RESULTS_FOLDER"] = "results/"

app.config["SECRET_KEY"] = secrets.token_hex()


RENAME_SURVEY_COLUMNS_DICT = [
    "E-mail",
    "Nome",
    "Turma",
    "Proficiencias",
    "Estagio de ferias",
    "Projetos escolhidos",
    "Dupla titulacao"
]

# Include jinja2 functions for formating values
env = Environment(
    autoescape=select_autoescape(['html', 'xml']),
)

# @env.add_filter
# def percent(value, decimals=2):
#     return "{:.{decimals}%}".format(value * 100, decimals=decimals)

app.jinja_env.environment = env


@app.route("/", methods=["GET"])
def index():
    session["secret_key"] = app.config["SECRET_KEY"]
    return render_template("index.html")


@app.route("/", methods=["POST"])
def upload_file():
    # secret_key = session.get("secret_key")
    # if secret_key is None:
    #     return render_template("index.html")
    
    if "survey" not in request.files:
        return redirect(request.url)
    
    survey = request.files["survey"]
    if survey.filename == "":
        return redirect(request.url)

    session["survey_filename"] = survey.filename
    column_names = {}

    control = request.files["control"]
    
    if survey and\
    (survey.filename.endswith(".xlsx") or\
     survey.filename.endswith(".xls")):
        filepath = os.path.join(app.config["UPLOAD_FOLDER"],
                                survey.filename)
        survey.save(filepath)

        df_survey = pd.read_excel(filepath)
        column_names.update({survey.filename: df_survey.columns.to_list()})

        if control and\
        (control.filename.endswith(".xlsx") or\
         control.filename.endswith(".xls")):
            filepath = os.path.join(app.config["UPLOAD_FOLDER"],
                                    control.filename)
            control.save(filepath)
            session["control_filename"] = control.filename

            df_control = pd.read_excel(filepath)
            column_names.update({control.filename: df_control.columns.to_list()})

        session.modified = True
        return render_template("select_columns.html",
                               column_names=column_names,
                               variables=RENAME_SURVEY_COLUMNS_DICT)
    return redirect(request.url)


@app.route("/model", methods=["POST"])
def call_model():
    df_column_matching = pd.DataFrame(columns=["File","Column name","Parameter"])
    i = 0
    for key,value in request.form.items():
        df_column_matching.loc[i] = [key.split("__")[1],
                                     value,
                                     key.split("__")[0]]
        i += 1

    df_column_matching = df_column_matching.dropna(subset=["Column name"])

    # TODO: field input error handling
    if df_column_matching["Parameter"].value_counts()["E-mail"] != 2:
        return redirect(request.url)


    # Migrated from sorteio_de_grupos.py with adaptation
    ## Data preparation
    df_survey = pd.read_excel(os.path.join(app.config["UPLOAD_FOLDER"],
                                           session.get("survey_filename")))
    
    df_survey_columns = df_column_matching[df_column_matching["File"] == session.get("survey_filename")].reset_index(drop=True)

    SURVEY_SHEET_COLUMNS = {}
    for i in range(df_survey_columns.shape[0]):
        dict_key = df_survey_columns.at[i,"Column name"]
        dict_value = df_survey_columns.at[i,"Parameter"]
        SURVEY_SHEET_COLUMNS.update({dict_key : dict_value})

    df_survey.columns = [col.replace('\n', ' ') for col in df_survey.columns]
    df_survey.columns = [col.strip() for col in df_survey.columns]

    df_survey = df_survey.loc[:, df_survey.columns.isin(SURVEY_SHEET_COLUMNS.keys())]
    df_survey = df_survey.rename(columns=SURVEY_SHEET_COLUMNS)

    df_survey["email original"] = df_survey["E-mail"]
    df_survey["E-mail"] = df_survey["E-mail"].str.lower()
    df_survey["E-mail"] = df_survey["E-mail"].str.replace("@.*",
                                                          "@al.insper.edu.br",
                                                          regex=True)
    mask = ~df_survey["E-mail"].str.contains("@")
    domain = pd.Series("@al.insper.edu.br",
                       index=range(len(df_survey.loc[mask, "E-mail"])))
    df_survey.loc[mask, "E-mail"] = df_survey.loc[mask, "E-mail"].str.cat(domain)
    
    # Extract project list from survey answers
    df_survey['project_list'] = df_survey["Projetos escolhidos"].str.split(', ')


    projects = pd.Series([item for sublist in df_survey["project_list"] for item in sublist]).unique()


    # Extract proficiency list from survey answers
    def split_proficiencies(input_str):
        items = []
        current = []
        depth = 0

        for char in input_str:
            if char == ',' and depth == 0:  # Split only on commas outside parentheses
                items.append(''.join(current).strip())
                current = []
            else:
                if char == '(':
                    depth += 1
                elif char == ')':
                    depth -= 1
                current.append(char)

        # Add the last segment
        if current:
            items.append(''.join(current).strip())

        return items

    df_survey["Proficiencias"] = df_survey["Proficiencias"].apply(split_proficiencies)

    proficiencies = pd.Series([item for sublist in df_survey["Proficiencias"] for item in sublist]).unique()


    # Convert internship variable to binary
    df_survey["Estagio de ferias"] = df_survey["Estagio de ferias"].replace({"Não": 0, "Sim": 1})

    # Control sheet
    df_control = pd.read_excel(os.path.join(app.config["UPLOAD_FOLDER"],
                                            session.get("control_filename")))

    df_control_columns = df_column_matching[df_column_matching["File"] == session.get("control_filename")].reset_index(drop=True)

    CONTROL_SHEET_COLUMNS = {}
    for i in range(df_control_columns.shape[0]):
        dict_key = df_control_columns.at[i,"Column name"]
        dict_value = df_control_columns.at[i,"Parameter"]
        CONTROL_SHEET_COLUMNS.update({dict_key : dict_value})

    df_control.columns = [col.replace('\n', ' ') for col in df_control.columns]
    df_control.columns = [col.strip() for col in df_control.columns]

    df_control = df_control.loc[:, df_control.columns.isin(CONTROL_SHEET_COLUMNS.keys())]
    df_control = df_control.rename(columns=CONTROL_SHEET_COLUMNS)
    df_control["Dupla titulacao"] = df_control["Dupla titulacao"].eq("DT").astype("int")

    df_merged = pd.merge(df_survey,
                         df_control,
                         how="left",
                         on="E-mail",
                         indicator=True)

    # TODO: list survey rows that were not found (_merge == left_only)
    df_merged["Dupla titulacao"].fillna(0, inplace=True)
    # Replace missing email with name
    df_merged["E-mail"].fillna(df_merged["Nome"], inplace=True)
    # Drop rows with neither email nor name
    df_merged = df_merged.dropna(subset=["E-mail"])
    ## End data preparation

    ## Setup model
    # Define the problem
    prob = pp.LpProblem("Project_Assignment", pp.LpMinimize)


    # Capacity of each project
    max_group_size = math.ceil(df_merged.shape[0] / projects.size)
    project_capacity = {project: max_group_size for project in projects}


    # Decision Variable
    assignments = pp.LpVariable.dicts("Assign",
                                      [(s, p) for s in df_merged["E-mail"]
                                              for p in projects],
                                      cat="Binary")

    # Objective: Minimize total preference score
    preference_cost = {}
    for project in projects:
        for _, student in df_merged.iterrows():
            if project in student['project_list']:
                preference_cost[(student["E-mail"],
                                 project)] = student['project_list'].index(project)
            else:
                preference_cost[(student["E-mail"],
                                 project)] = 15

    # Constraint 1: Each student must be assigned to exactly one project
    for student in df_merged["E-mail"]:
        prob += pp.lpSum(assignments[(student, project)]
                         for project in projects) == 1

    
    # Constraint 2: Each project cannot exceed its capacity
    for project in projects:
        prob += pp.lpSum(assignments[(student, project)]
                         for student in df_merged["E-mail"]
                         ) <= project_capacity[project]

    # Constraint 3: No more than 1 Double Degree in a group
    for project in projects:
        prob += pp.lpSum(
            df_merged[df_merged["E-mail"] == s]["Dupla titulacao"] * assignments[
                (s, project)
            ] for s in df_merged["E-mail"]) <= 1
           

    # Soft constraint 1: Proficiencies
    w_proficiency = 0.5    # The weight given to proficiency variety in a group
    present_proficiency = pp.LpVariable.dicts("Present",
                                              [(g, p)
                                               for g in projects
                                               for p in proficiencies],
                                              cat="Binary")

    # Proficiency presence
    for proj in projects:
        for p in proficiencies:
            prob += (
                pp.lpSum(assignments[s,proj]
                         for s in df_merged["E-mail"]
                         if p in df_merged[df_merged["E-mail"] == s]\
                         ["Proficiencias"].iloc[0]) >= present_proficiency[proj, p]
            )
            prob += (
                present_proficiency[proj, p] <= pp.lpSum(assignments[s, proj]
                                                         for s in df_merged["E-mail"]
                                                         if p in df_merged[df_merged["E-mail"] == s]["Proficiencias"].iloc[0])
        )


    # Soft constraint 2: Internships
    w_internship = 0.5     # The weight given to variety of internship experience in a group
    count_with_internships = pp.LpVariable.dicts("WithInternships",
                                                 projects,
                                                 lowBound=0,
                                                 cat="Continuous")
    count_without_internships = pp.LpVariable.dicts("WithoutInternships",
                                                    projects,
                                                    lowBound=0,
                                                    cat="Continuous")

    abs_diff_internships = pp.LpVariable.dicts("AbsDiffInternships",
                                               projects,
                                               lowBound=0,
                                               cat="Continuous")

    # Internship count
    for proj in projects:
        prob += count_with_internships[proj] == pp.lpSum(
            assignments[s, proj] * df_merged[df_merged["E-mail"] == s]\
            ["Estagio de ferias"].iloc[0]
            for s in df_merged["E-mail"]
        )
        prob += count_without_internships[proj] == pp.lpSum(
            assignments[s, proj] * (1 - df_merged[df_merged["E-mail"] == s]\
                                    ["Estagio de ferias"].iloc[0])
            for s in df_merged["E-mail"])

    # Absolute difference for internships
    for proj in projects:
        prob += abs_diff_internships[proj] >= count_with_internships[proj] - count_without_internships[proj]
        prob += abs_diff_internships[proj] >= count_without_internships[proj] - count_with_internships[proj]


    # Add soft constraints to Objective Function according to defined weights
    prob += (
        pp.lpSum(preference_cost[s, proj] * assignments[s, proj]
                 for s in df_merged["E-mail"]
                 for proj in projects)
        + w_proficiency * (
            len(projects) * len(proficiencies) - pp.lpSum(present_proficiency[proj, p]
                                                          for proj in projects
                                                          for p in proficiencies)
        )
        + w_internship * pp.lpSum(abs_diff_internships[proj] for proj in projects)
    )
    
    # Solve the problem
    prob.solve()
    ## End - Setup model: model already run

    ## Analysis and final outputs
    # Extract the results
    assigned_data = []

    for s in df_merged["E-mail"]:
        for proj in projects:
            if assignments[s, proj].varValue == 1:
                assigned_data.append({"E-mail": s, "Group": proj})

    # Convert to DataFrame
    df_assignments = pd.DataFrame(assigned_data)
    #pprint(Counter(df_assignments["Group"]))

    # Group the data by group
    df_summary = pd.merge(df_assignments, df_merged, on="E-mail")
    df_summary["Proficiencias"] = df_summary["Proficiencias"].apply(lambda x: ", ".join(x))

    # Aggregate the data
    summary_display = df_summary.groupby("Group").agg({
        "E-mail": "count",
        "Proficiencias": "nunique",
        "Estagio de ferias": "mean",
        "Dupla titulacao": "sum",
        "Turma": "nunique",
    })

    filename = "Grupos_REP.xlsx"
    filepath = os.path.join(app.config["RESULTS_FOLDER"],
                                filename)
    results = df_summary.to_excel(filepath)


    return render_template("model_results.html",
                           summary=summary_display,
                           results_filepath=filepath)

@app.route("/download_results", methods=["POST"])
def download_results():
    filepath = request.form.get("filepath")
    return send_file(filepath, as_attachment=True)


if __name__ == "__main__":
    app.run(debug=True)
