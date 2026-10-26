#include <clang/AST/ASTConsumer.h>
#include <clang/AST/ASTContext.h>
#include <clang/AST/DeclCXX.h>
#include <clang/AST/DeclTemplate.h>
#include <clang/AST/RawCommentList.h>
#include <clang/AST/RecursiveASTVisitor.h>
#include <clang/Basic/Diagnostic.h>
#include <clang/Basic/SourceManager.h>
#include <clang/Basic/Version.h>
#include <clang/Frontend/CompilerInstance.h>
#include <clang/Frontend/FrontendAction.h>
#include <clang/Index/USRGeneration.h>
#include <clang/Lex/Lexer.h>
#include <clang/Lex/HeaderSearch.h>
#include <clang/Lex/PPCallbacks.h>
#include <clang/Lex/Preprocessor.h>
#include <clang/Tooling/CompilationDatabase.h>
#include <clang/Tooling/Tooling.h>
#include <llvm/ADT/SmallString.h>
#include <llvm/Support/JSON.h>
#include <llvm/Support/MemoryBuffer.h>
#include <llvm/Support/Error.h>
#include <llvm/Support/raw_ostream.h>

#include <algorithm>
#include <filesystem>
#include <iostream>
#include <memory>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

namespace {

using llvm::json::Array;
using llvm::json::Object;
using llvm::json::Value;

struct FrontendData {
  Array Declarations;
  Array NonFunctionDeclarations;
  Array Calls;
  Array Preprocessing;
  Array DocumentationComments;
  Array Includes;
  Array SearchDirectories;
  Array Diagnostics;
  std::vector<std::string> DependencyPaths;
  std::string TargetTriple;
  std::string Sysroot;
  int64_t OmittedHeaderFunctionDeclarations = 0;
  int64_t OmittedHeaderMacroDefinitions = 0;
  int64_t OmittedHeaderPreprocessingEvents = 0;
};

Value coordinate(clang::SourceLocation Location,
                 const clang::SourceManager &SM) {
  if (Location.isInvalid())
    return nullptr;
  clang::SourceLocation FileLocation = SM.getFileLoc(Location);
  if (FileLocation.isInvalid())
    return nullptr;
  clang::FileID File = SM.getFileID(FileLocation);
  unsigned Offset = SM.getFileOffset(FileLocation);
  return Object{{"path", SM.getFilename(FileLocation).str()},
                {"line", static_cast<int64_t>(SM.getLineNumber(File, Offset))},
                {"column", static_cast<int64_t>(SM.getColumnNumber(File, Offset))},
                {"offset", static_cast<int64_t>(Offset)}};
}

Value location(clang::SourceLocation Location,
               const clang::SourceManager &SM) {
  Value Spelling = coordinate(SM.getSpellingLoc(Location), SM);
  Value Expansion = coordinate(SM.getExpansionLoc(Location), SM);
  return Object{{"spelling", std::move(Spelling)},
                {"expansion", std::move(Expansion)},
                {"is_macro", Location.isMacroID()}};
}

Value sourceRange(clang::SourceRange Range, const clang::SourceManager &SM) {
  return Object{{"begin", location(Range.getBegin(), SM)},
                {"end", location(Range.getEnd(), SM)}};
}

std::string sourceText(clang::SourceRange Range,
                       const clang::SourceManager &SM,
                       const clang::LangOptions &LangOpts) {
  if (Range.isInvalid())
    return {};
  bool Invalid = false;
  llvm::StringRef Text = clang::Lexer::getSourceText(
      clang::CharSourceRange::getTokenRange(Range), SM, LangOpts, &Invalid);
  return Invalid ? std::string() : Text.str();
}

bool samePhysicalPath(const std::string &Left, const std::string &Right) {
  if (Left.empty() || Right.empty())
    return false;
  std::error_code LeftError;
  std::error_code RightError;
  const std::filesystem::path CanonicalLeft =
      std::filesystem::weakly_canonical(Left, LeftError);
  const std::filesystem::path CanonicalRight =
      std::filesystem::weakly_canonical(Right, RightError);
  if (LeftError || RightError)
    return std::filesystem::path(Left).lexically_normal() ==
           std::filesystem::path(Right).lexically_normal();
  return CanonicalLeft == CanonicalRight;
}

bool isInPhysicalFile(clang::SourceLocation Location,
                      const clang::SourceManager &SM,
                      const std::string &Path) {
  if (Location.isInvalid() || Path.empty())
    return false;
  const clang::SourceLocation Spelling =
      SM.getFileLoc(SM.getSpellingLoc(Location));
  return samePhysicalPath(SM.getFilename(Spelling).str(), Path);
}

std::string usr(const clang::Decl *Declaration) {
  llvm::SmallString<128> Buffer;
  if (clang::index::generateUSRForDecl(Declaration, Buffer))
    return {};
  return Buffer.str().str();
}

std::string semanticUSR(const clang::NamedDecl *Declaration) {
  std::string Identity = usr(Declaration);
  if (Identity.empty() || Declaration->hasExternalFormalLinkage())
    return Identity;
  clang::SourceManager &SM = Declaration->getASTContext().getSourceManager();
  const clang::SourceLocation Location =
      SM.getFileLoc(Declaration->getLocation());
  std::string Path = SM.getFilename(Location).str();
  const clang::SourceLocation MainLocation =
      SM.getLocForStartOfFile(SM.getMainFileID());
  std::string TranslationUnit = SM.getFilename(MainLocation).str();
  if (Path.empty() || TranslationUnit.empty())
    return Identity;
  std::error_code Error;
  std::filesystem::path Canonical = std::filesystem::weakly_canonical(Path, Error);
  if (!Error)
    Path = Canonical.string();
  Error.clear();
  std::filesystem::path CanonicalTranslationUnit =
      std::filesystem::weakly_canonical(TranslationUnit, Error);
  if (!Error)
    TranslationUnit = CanonicalTranslationUnit.string();
  return "internal:" + TranslationUnit + ":" + Path + ":" + Identity;
}

class ValueReturnVisitor final
    : public clang::RecursiveASTVisitor<ValueReturnVisitor> {
public:
  bool VisitReturnStmt(clang::ReturnStmt *Return) {
    HasValueReturn = HasValueReturn || Return->getRetValue() != nullptr;
    return true;
  }

  bool HasValueReturn = false;
};

bool hasValueReturn(const clang::FunctionDecl *Function) {
  if (!Function->doesThisDeclarationHaveABody())
    return false;
  ValueReturnVisitor Visitor;
  Visitor.TraverseStmt(Function->getBody());
  return Visitor.HasValueReturn;
}

std::string functionSignature(const clang::FunctionDecl *Function) {
  clang::PrintingPolicy Policy(Function->getASTContext().getLangOpts());
  Policy.SuppressScope = false;
  std::string Result;
  if (!llvm::isa<clang::CXXConstructorDecl>(Function) &&
      !llvm::isa<clang::CXXDestructorDecl>(Function) &&
      !llvm::isa<clang::CXXConversionDecl>(Function))
    Result = Function->getReturnType().getAsString(Policy) + " ";
  Result += Function->getQualifiedNameAsString() + "(";
  for (unsigned Index = 0; Index < Function->getNumParams(); ++Index) {
    if (Index)
      Result += ", ";
    const clang::ParmVarDecl *Parameter = Function->getParamDecl(Index);
    Result += Parameter->getType().getAsString(Policy);
    if (!Parameter->getName().empty())
      Result += " " + Parameter->getNameAsString();
  }
  if (Function->isVariadic()) {
    if (Function->getNumParams())
      Result += ", ";
    Result += "...";
  }
  Result += ")";
  if (const auto *Method = llvm::dyn_cast<clang::CXXMethodDecl>(Function)) {
    if (Method->isConst())
      Result += " const";
    if (Method->isVolatile())
      Result += " volatile";
    if (Method->getRefQualifier() == clang::RQ_LValue)
      Result += " &";
    else if (Method->getRefQualifier() == clang::RQ_RValue)
      Result += " &&";
    if (Method->isPureVirtual())
      Result += " = 0";
  }
  if (Function->isDeletedAsWritten())
    Result += " = delete";
  else if (Function->isDefaulted())
    Result += " = default";
  return Result;
}

std::string functionType(const clang::FunctionDecl *Function) {
  clang::PrintingPolicy Policy(Function->getASTContext().getLangOpts());
  return Function->getType().getAsString(Policy);
}

std::string declarationKind(const clang::FunctionDecl *Function) {
  if (Function->isImplicit())
    return "implicit";
  switch (Function->getTemplateSpecializationKind()) {
  case clang::TSK_ImplicitInstantiation:
    return "template_instantiation";
  case clang::TSK_ExplicitInstantiationDeclaration:
  case clang::TSK_ExplicitInstantiationDefinition:
    return "explicit_template_instantiation";
  case clang::TSK_Undeclared:
  case clang::TSK_ExplicitSpecialization:
    return "written";
  }
  return "written";
}

std::string templateOrigin(clang::TemplateSpecializationKind Kind) {
  switch (Kind) {
  case clang::TSK_ImplicitInstantiation:
    return "template_instantiation";
  case clang::TSK_ExplicitInstantiationDeclaration:
  case clang::TSK_ExplicitInstantiationDefinition:
    return "explicit_template_instantiation";
  case clang::TSK_Undeclared:
  case clang::TSK_ExplicitSpecialization:
    return {};
  }
  return {};
}

std::string namedDeclarationOrigin(const clang::NamedDecl *Declaration,
                                  const clang::SourceManager &SM) {
  if (Declaration->isImplicit())
    return "implicit";
  if (const auto *Function = llvm::dyn_cast<clang::FunctionDecl>(Declaration))
    if (std::string Origin =
            templateOrigin(Function->getTemplateSpecializationKind());
        !Origin.empty())
      return Origin;
  if (const auto *Variable =
          llvm::dyn_cast<clang::VarTemplateSpecializationDecl>(Declaration))
    if (std::string Origin = templateOrigin(Variable->getSpecializationKind());
        !Origin.empty())
      return Origin;
  if (const auto *Specialization =
          llvm::dyn_cast<clang::ClassTemplateSpecializationDecl>(Declaration))
    if (std::string Origin =
            templateOrigin(Specialization->getSpecializationKind());
        !Origin.empty())
      return Origin;
  if (const auto *Context = llvm::dyn_cast<clang::ClassTemplateSpecializationDecl>(
          Declaration->getDeclContext()))
    if (std::string Origin = templateOrigin(Context->getSpecializationKind());
        !Origin.empty())
      return Origin;
  const clang::SourceLocation Location = Declaration->getLocation();
  if (Location.isMacroID())
    return SM.isMacroArgExpansion(Location) ? "macro_argument"
                                            : "macro_replacement";
  return "source_written";
}

std::string declarationDeclKind(const clang::FunctionDecl *Function) {
  if (llvm::isa<clang::CXXConstructorDecl>(Function))
    return "constructor";
  if (llvm::isa<clang::CXXDestructorDecl>(Function))
    return "destructor";
  if (llvm::isa<clang::CXXConversionDecl>(Function))
    return "conversion";
  if (llvm::isa<clang::CXXMethodDecl>(Function))
    return "method";
  return "function";
}

std::string namedDeclarationKind(const clang::NamedDecl *Declaration) {
  if (const auto *Record = llvm::dyn_cast<clang::RecordDecl>(Declaration)) {
    if (Record->isUnion())
      return "union";
    if (const auto *CXXRecord = llvm::dyn_cast<clang::CXXRecordDecl>(Record))
      return CXXRecord->isStruct() ? "struct" : "class";
    return Record->isStruct() ? "struct" : "class";
  }
  if (llvm::isa<clang::EnumDecl>(Declaration))
    return "enum";
  if (llvm::isa<clang::EnumConstantDecl>(Declaration))
    return "constant";
  if (const auto *Typedef = llvm::dyn_cast<clang::TypedefNameDecl>(Declaration))
    return llvm::isa<clang::TypeAliasDecl>(Typedef) ? "type_alias" : "typedef";
  if (llvm::isa<clang::NamespaceDecl>(Declaration))
    return "namespace";
  if (llvm::isa<clang::FieldDecl>(Declaration))
    return "variable";
  if (const auto *Variable = llvm::dyn_cast<clang::VarDecl>(Declaration))
    return Variable->isConstexpr() || Variable->getType().isConstQualified()
               ? "constant"
               : "variable";
  return "declaration";
}

bool namedDeclarationIsDefinition(const clang::NamedDecl *Declaration) {
  if (const auto *Tag = llvm::dyn_cast<clang::TagDecl>(Declaration))
    return Tag->isThisDeclarationADefinition();
  if (const auto *Variable = llvm::dyn_cast<clang::VarDecl>(Declaration))
    return Variable->isThisDeclarationADefinition();
  if (llvm::isa<clang::FieldDecl>(Declaration) ||
      llvm::isa<clang::EnumConstantDecl>(Declaration) ||
      llvm::isa<clang::TypedefNameDecl>(Declaration) ||
      llvm::isa<clang::NamespaceDecl>(Declaration))
    return true;
  return false;
}

Object methodQualifiers(const clang::FunctionDecl *Function) {
  Object Qualifiers{{"is_method", false}};
  if (const auto *Method = llvm::dyn_cast<clang::CXXMethodDecl>(Function)) {
    std::string RefQualifier = "none";
    switch (Method->getRefQualifier()) {
    case clang::RQ_None:
      RefQualifier = "none";
      break;
    case clang::RQ_LValue:
      RefQualifier = "lvalue";
      break;
    case clang::RQ_RValue:
      RefQualifier = "rvalue";
      break;
    }
    Qualifiers["is_method"] = true;
    Qualifiers["is_const"] = Method->isConst();
    Qualifiers["is_volatile"] = Method->isVolatile();
    Qualifiers["is_static"] = Method->isStatic();
    Qualifiers["is_virtual"] = Method->isVirtual();
    Qualifiers["is_pure_virtual"] = Method->isPureVirtual();
    Qualifiers["ref_qualifier"] = RefQualifier;
  }
  if (const auto *Constructor =
          llvm::dyn_cast<clang::CXXConstructorDecl>(Function)) {
    std::string ConstructorKind = "other";
    if (Constructor->isDefaultConstructor())
      ConstructorKind = "default";
    else if (Constructor->isCopyOrMoveConstructor())
      ConstructorKind = "copy_or_move";
    else if (Constructor->isConvertingConstructor(false))
      ConstructorKind = "converting";
    Qualifiers["constructor_kind"] = ConstructorKind;
    Qualifiers["is_explicit"] = Constructor->isExplicit();
  }
  return Qualifiers;
}

Value declarationIdentity(const clang::FunctionDecl *Function) {
  std::string ParentUSR;
  if (const clang::FunctionTemplateDecl *Template = Function->getPrimaryTemplate())
    ParentUSR = semanticUSR(Template->getTemplatedDecl());
  const clang::SourceManager &SM = Function->getASTContext().getSourceManager();
  return Object{{"usr", semanticUSR(Function)},
                {"kind", declarationKind(Function)},
                {"provenance", namedDeclarationOrigin(Function, SM)},
                {"decl_kind", declarationDeclKind(Function)},
                {"instantiated_from", ParentUSR.empty() ? Value(nullptr)
                                                          : Value(ParentUSR)}};
}

Value parameter(const clang::ParmVarDecl *Parameter) {
  clang::PrintingPolicy Policy(Parameter->getASTContext().getLangOpts());
  return Object{{"name", Parameter->getNameAsString()},
                {"type", Parameter->getType().getAsString(Policy)},
                {"location", location(Parameter->getLocation(),
                                       Parameter->getASTContext().getSourceManager())}};
}

std::string conditionValue(clang::PPCallbacks::ConditionValueKind Value) {
  switch (Value) {
  case clang::PPCallbacks::CVK_True:
    return "true";
  case clang::PPCallbacks::CVK_False:
    return "false";
  case clang::PPCallbacks::CVK_NotEvaluated:
    return "not_evaluated";
  }
  return "unknown";
}

class CallbackCollector final : public clang::PPCallbacks {
public:
  CallbackCollector(FrontendData &Data, const clang::SourceManager &SM,
                    const clang::LangOptions &LangOpts, bool FullCapture,
                    std::string ProjectionFile)
      : Data(Data), SM(SM), LangOpts(LangOpts), FullCapture(FullCapture),
        ProjectionFile(std::move(ProjectionFile)) {}

  void InclusionDirective(clang::SourceLocation HashLoc, const clang::Token &,
                          llvm::StringRef FileName, bool IsAngled,
                          clang::CharSourceRange, clang::OptionalFileEntryRef File,
                          llvm::StringRef SearchPath, llvm::StringRef RelativePath,
                          const clang::Module *, bool ModuleImported,
                          clang::SrcMgr::CharacteristicKind) override {
    if (!keepsLocation(HashLoc))
      return;
    std::string Resolved = File ? File->getName().str() : std::string();
    if (!Resolved.empty())
      Data.DependencyPaths.push_back(Resolved);
    Data.Includes.push_back(Object{
        {"spelled_path", FileName.str()},
        {"resolved_path", Resolved.empty() ? Value(nullptr) : Value(Resolved)},
        {"angled", IsAngled},
        {"search_path", SearchPath.str()},
        {"relative_path", RelativePath.str()},
        {"module_imported", ModuleImported},
        {"location", location(HashLoc, SM)}});
  }

  void MacroDefined(const clang::Token &Name,
                    const clang::MacroDirective *Directive) override {
    const clang::MacroInfo *Info = Directive ? Directive->getMacroInfo() : nullptr;
    if (!Info)
      return;
    MacroDefinitions[Info] = MacroDefinitionRecord{
        clang::Lexer::getSpelling(Name, SM, LangOpts), Name.getLocation(), Info};
    if (keepsLocation(Name.getLocation()) &&
        (FullCapture || !ProjectionFile.empty() ||
         isMainExpansion(Name.getLocation()))) {
      Data.Preprocessing.push_back(macroDefinitionEvent(MacroDefinitions[Info]));
      EmittedMacroDefinitions.insert(Info);
    } else {
      ++Data.OmittedHeaderMacroDefinitions;
    }
  }

  void MacroUndefined(const clang::Token &Name, const clang::MacroDefinition &,
                      const clang::MacroDirective *) override {
    if (keepsLocation(Name.getLocation()) &&
        (FullCapture || !ProjectionFile.empty() ||
         isMainExpansion(Name.getLocation()))) {
      Data.Preprocessing.push_back(Object{
          {"kind", "macro_undefinition"},
          {"name", clang::Lexer::getSpelling(Name, SM, LangOpts)},
          {"location", location(Name.getLocation(), SM)}});
    } else {
      ++Data.OmittedHeaderPreprocessingEvents;
    }
  }

  void MacroExpands(const clang::Token &Name,
                    const clang::MacroDefinition &Definition,
                    clang::SourceRange Range, const clang::MacroArgs *) override {
    if (!keepsLocation(Name.getLocation()) ||
        (ProjectionFile.empty() && !FullCapture &&
         !isMainExpansion(Name.getLocation()))) {
      ++Data.OmittedHeaderPreprocessingEvents;
      return;
    }
    const clang::MacroInfo *Info = Definition.getMacroInfo();
    if (!FullCapture && Info && !EmittedMacroDefinitions.contains(Info)) {
      auto Found = MacroDefinitions.find(Info);
      if (Found != MacroDefinitions.end()) {
        Data.Preprocessing.push_back(macroDefinitionEvent(Found->second));
        EmittedMacroDefinitions.insert(Info);
        --Data.OmittedHeaderMacroDefinitions;
      }
    }
    Data.Preprocessing.push_back(Object{
        {"kind", "macro_expansion"},
        {"name", clang::Lexer::getSpelling(Name, SM, LangOpts)},
        {"invocation", sourceText(Range, SM, LangOpts)},
        {"range", sourceRange(Range, SM)},
        {"location", location(Name.getLocation(), SM)}});
  }

  void If(clang::SourceLocation Loc, clang::SourceRange Condition,
          ConditionValueKind Result) override {
    conditional("if", Loc, Condition, Result);
  }

  void Elif(clang::SourceLocation Loc, clang::SourceRange Condition,
            ConditionValueKind Result, clang::SourceLocation) override {
    conditional("elif", Loc, Condition, Result);
  }

  void Ifdef(clang::SourceLocation Loc, const clang::Token &Name,
             const clang::MacroDefinition &Definition) override {
    conditionalName("ifdef", Loc, Name, static_cast<bool>(Definition));
  }

  void Ifndef(clang::SourceLocation Loc, const clang::Token &Name,
              const clang::MacroDefinition &Definition) override {
    conditionalName("ifndef", Loc, Name, static_cast<bool>(Definition));
  }

  void Else(clang::SourceLocation Loc, clang::SourceLocation) override {
    if (!keepsLocation(Loc) ||
        (ProjectionFile.empty() && !FullCapture && !isMainExpansion(Loc))) {
      ++Data.OmittedHeaderPreprocessingEvents;
      return;
    }
    Data.Preprocessing.push_back(Object{
        {"kind", "else"}, {"location", location(Loc, SM)}});
  }

  void Endif(clang::SourceLocation Loc, clang::SourceLocation) override {
    if (!keepsLocation(Loc) ||
        (ProjectionFile.empty() && !FullCapture && !isMainExpansion(Loc))) {
      ++Data.OmittedHeaderPreprocessingEvents;
      return;
    }
    Data.Preprocessing.push_back(Object{
        {"kind", "endif"}, {"location", location(Loc, SM)}});
  }

private:
  struct MacroDefinitionRecord {
    std::string Name;
    clang::SourceLocation Location;
    const clang::MacroInfo *Info;
  };

  bool isMainExpansion(clang::SourceLocation Loc) const {
    return SM.isWrittenInMainFile(SM.getExpansionLoc(Loc));
  }

  bool keepsLocation(clang::SourceLocation Loc) const {
    return ProjectionFile.empty() || isInPhysicalFile(Loc, SM, ProjectionFile);
  }

  Value macroDefinitionEvent(const MacroDefinitionRecord &Record) const {
    Array Replacement;
    bool Truncated = false;
    unsigned Count = 0;
    for (const clang::Token &Token : Record.Info->tokens()) {
      if (Count++ == 96) {
        Truncated = true;
        break;
      }
      Replacement.push_back(clang::Lexer::getSpelling(Token, SM, LangOpts));
    }
    Array Parameters;
    for (const clang::IdentifierInfo *Parameter : Record.Info->params())
      Parameters.push_back(Parameter->getName().str());
    const std::string SourceText = sourceText(
        clang::SourceRange(Record.Info->getDefinitionLoc(),
                           Record.Info->getDefinitionEndLoc()),
        SM, LangOpts);
    return Object{{"kind", "macro_definition"},
                  {"name", Record.Name},
                  {"replacement", std::move(Replacement)},
                  {"replacement_truncated", Truncated},
                  {"function_like", Record.Info->isFunctionLike()},
                  {"parameters", std::move(Parameters)},
                  {"source_text", SourceText},
                  {"location", location(Record.Location, SM)}};
  }

  void conditional(llvm::StringRef Kind, clang::SourceLocation Loc,
                   clang::SourceRange Condition,
                   ConditionValueKind Result) {
    if (!keepsLocation(Loc) ||
        (ProjectionFile.empty() && !FullCapture && !isMainExpansion(Loc))) {
      ++Data.OmittedHeaderPreprocessingEvents;
      return;
    }
    Data.Preprocessing.push_back(Object{
        {"kind", Kind.str()},
        {"condition", sourceText(Condition, SM, LangOpts)},
        {"result", conditionValue(Result)},
        {"range", sourceRange(Condition, SM)},
        {"location", location(Loc, SM)}});
  }

  void conditionalName(llvm::StringRef Kind, clang::SourceLocation Loc,
                       const clang::Token &Name, bool IsDefined) {
    if (!keepsLocation(Loc) ||
        (ProjectionFile.empty() && !FullCapture && !isMainExpansion(Loc))) {
      ++Data.OmittedHeaderPreprocessingEvents;
      return;
    }
    Data.Preprocessing.push_back(Object{
        {"kind", Kind.str()},
        {"name", clang::Lexer::getSpelling(Name, SM, LangOpts)},
        {"macro_defined", IsDefined},
        {"location", location(Loc, SM)}});
  }

  FrontendData &Data;
  const clang::SourceManager &SM;
  const clang::LangOptions &LangOpts;
  bool FullCapture;
  std::string ProjectionFile;
  std::unordered_map<const clang::MacroInfo *, MacroDefinitionRecord>
      MacroDefinitions;
  std::unordered_set<const clang::MacroInfo *> EmittedMacroDefinitions;
};

class FrontendVisitor final : public clang::RecursiveASTVisitor<FrontendVisitor> {
public:
  FrontendVisitor(clang::ASTContext &Context, FrontendData &Data,
                  llvm::StringRef MainFile, llvm::StringRef RepositoryRoot,
                  bool FullCapture, llvm::StringRef ProjectionFile)
      : Context(Context), Data(Data), MainFile(MainFile.str()),
        RepositoryRoot(RepositoryRoot.str()), FullCapture(FullCapture),
        ProjectionFile(ProjectionFile.str()) {}

  bool shouldVisitTemplateInstantiations() const { return true; }

  bool TraverseDecl(clang::Decl *Declaration) {
    if (!Declaration)
      return true;
    auto *Function = llvm::dyn_cast<clang::FunctionDecl>(Declaration);
    if (!Function)
      return clang::RecursiveASTVisitor<FrontendVisitor>::TraverseDecl(
          Declaration);
    const std::string PreviousCallerUSR = CurrentCallerUSR;
    const std::string PreviousCallerName = CurrentCallerName;
    const std::string PreviousCallerQualifiedName = CurrentCallerQualifiedName;
    const std::string PreviousCallerOrigin = CurrentCallerOrigin;
    CurrentCallerUSR = semanticUSR(Function);
    CurrentCallerName = Function->getNameAsString();
    CurrentCallerQualifiedName = Function->getQualifiedNameAsString();
    CurrentCallerOrigin = declarationKind(Function);
    const bool Traversed =
        clang::RecursiveASTVisitor<FrontendVisitor>::TraverseDecl(Declaration);
    CurrentCallerUSR = PreviousCallerUSR;
    CurrentCallerName = PreviousCallerName;
    CurrentCallerQualifiedName = PreviousCallerQualifiedName;
    CurrentCallerOrigin = PreviousCallerOrigin;
    return Traversed;
  }

  bool VisitFunctionDecl(clang::FunctionDecl *Function) {
    if (Function->getNameAsString().empty())
      return true;
    clang::SourceManager &SM = Context.getSourceManager();
    clang::SourceLocation Location = Function->getLocation();
    std::string Path = SM.getFilename(SM.getFileLoc(Location)).str();
    bool MainExpansion =
        SM.isWrittenInMainFile(SM.getExpansionLoc(Location));
    if ((!ProjectionFile.empty() &&
         !isInPhysicalFile(Location, SM, ProjectionFile)) ||
        (ProjectionFile.empty() && !FullCapture && !MainExpansion)) {
      ++Data.OmittedHeaderFunctionDeclarations;
      return true;
    }
    if (FullCapture &&
        (Path.empty() || (!SM.isWrittenInMainFile(Location) &&
                          (SM.isInSystemHeader(Location) ||
                           !withinRepository(Path)))))
      return true;
    Array Parameters;
    for (const clang::ParmVarDecl *Parameter : Function->parameters())
      Parameters.push_back(parameter(Parameter));
    const auto *Owner =
        llvm::dyn_cast<clang::NamedDecl>(Function->getDeclContext());
    Object DeclarationRecord{
        {"identity", declarationIdentity(Function)},
        {"decl_kind", declarationDeclKind(Function)},
        {"native_decl_kind",
         static_cast<const clang::Decl *>(Function)->getDeclKindName()},
        {"name", Function->getNameAsString()},
        {"qualified_name", Function->getQualifiedNameAsString()},
        {"signature", functionSignature(Function)},
        {"signature_kind", "derived_display_only"},
        {"function_type", functionType(Function)},
        {"lexical_owner",
         Owner ? Owner->getQualifiedNameAsString() : std::string()},
        {"owner_usr", Owner ? semanticUSR(Owner) : std::string()},
        {"owner_location", Owner ? location(Owner->getLocation(), SM) : Value(nullptr)},
        {"has_prototype", Function->hasPrototype()},
        {"is_variadic", Function->isVariadic()},
        {"method_qualifiers", methodQualifiers(Function)},
        {"is_definition", Function->isThisDeclarationADefinition()},
        {"returns_value", hasValueReturn(Function)},
        {"parameters", std::move(Parameters)},
        {"location", location(Location, SM)},
        {"range", sourceRange(Function->getSourceRange(), SM)}};
    if (const auto *Method = llvm::dyn_cast<clang::CXXMethodDecl>(Function)) {
      clang::AccessSpecifier Access = Method->getAccess();
      if (Access == clang::AS_none) {
        if (const auto *Record =
                llvm::dyn_cast<clang::CXXRecordDecl>(Method->getParent()))
          Access = Record->isClass() ? clang::AS_private : clang::AS_public;
      }
      if (Access != clang::AS_none)
        DeclarationRecord["is_public"] = Access == clang::AS_public;
    } else {
      DeclarationRecord["is_public"] =
          Function->getStorageClass() != clang::SC_Static;
    }
    if (const clang::RawComment *Comment =
            Context.getRawCommentForAnyRedecl(Function)) {
      if (Comment->isDocumentation()) {
        DeclarationRecord["documentation"] = Comment->getFormattedText(
            SM, Context.getDiagnostics());
        DeclarationRecord["documentation_location"] =
            location(Comment->getBeginLoc(), SM);
        DeclarationRecord["documentation_range"] =
            sourceRange(Comment->getSourceRange(), SM);
      }
    }
    Data.Declarations.push_back(std::move(DeclarationRecord));
    return true;
  }

  bool VisitNamedDecl(clang::NamedDecl *Declaration) {
    if (llvm::isa<clang::FunctionDecl>(Declaration) ||
        llvm::isa<clang::ParmVarDecl>(Declaration) ||
        llvm::isa<clang::TemplateTypeParmDecl>(Declaration) ||
        llvm::isa<clang::NonTypeTemplateParmDecl>(Declaration) ||
        llvm::isa<clang::TemplateTemplateParmDecl>(Declaration) ||
        Declaration->getNameAsString().empty())
      return true;
    clang::SourceManager &SM = Context.getSourceManager();
    const clang::SourceLocation Location = Declaration->getLocation();
    if ((!ProjectionFile.empty() &&
         !isInPhysicalFile(Location, SM, ProjectionFile)) ||
        (ProjectionFile.empty() &&
         !SM.isWrittenInMainFile(SM.getExpansionLoc(Location))))
      return true;
    clang::PrintingPolicy Policy(Context.getLangOpts());
    std::string Type;
    if (const auto *ValueDeclaration =
            llvm::dyn_cast<clang::ValueDecl>(Declaration))
      Type = ValueDeclaration->getType().getAsString(Policy);
    const auto *Owner =
        llvm::dyn_cast<clang::NamedDecl>(Declaration->getDeclContext());
    Value OwnerUSR = Owner ? Value(semanticUSR(Owner)) : Value(nullptr);
    Value OwnerName =
        Owner ? Value(Owner->getQualifiedNameAsString()) : Value(nullptr);
    Value OwnerLocation =
        Owner ? location(Owner->getLocation(), SM) : Value(nullptr);
    Value Access = nullptr;
    if (Owner && llvm::isa<clang::CXXRecordDecl>(Owner) &&
        Declaration->getAccess() != clang::AS_none) {
      switch (Declaration->getAccess()) {
      case clang::AS_public:
        Access = "public";
        break;
      case clang::AS_protected:
        Access = "protected";
        break;
      case clang::AS_private:
        Access = "private";
        break;
      case clang::AS_none:
        break;
      }
    }
    Value EnumOrdinal = nullptr;
    if (const auto *Enumerator =
            llvm::dyn_cast<clang::EnumConstantDecl>(Declaration)) {
      if (const auto *Enum = llvm::dyn_cast<clang::EnumDecl>(Owner)) {
        int64_t Ordinal = 1;
        for (const clang::EnumConstantDecl *Item : Enum->enumerators()) {
          if (Item == Enumerator) {
            EnumOrdinal = Ordinal;
            break;
          }
          ++Ordinal;
        }
      }
    }
    Object Record{
        {"identity", Object{{"usr", semanticUSR(Declaration)},
                             {"kind", namedDeclarationOrigin(Declaration, SM)},
                             {"provenance",
                              namedDeclarationOrigin(Declaration, SM)}}},
        {"decl_kind", Declaration->getDeclKindName()},
        {"entity_kind", namedDeclarationKind(Declaration)},
        {"name", Declaration->getNameAsString()},
        {"qualified_name", Declaration->getQualifiedNameAsString()},
        {"type", Type},
        {"is_file_scope", Declaration->getDeclContext()->isTranslationUnit()},
        {"owner_usr", std::move(OwnerUSR)},
        {"owner_name", std::move(OwnerName)},
        {"owner_location", std::move(OwnerLocation)},
        {"owner_kind", Owner ? Owner->getDeclKindName() : std::string()},
        {"access", std::move(Access)},
        {"is_definition", namedDeclarationIsDefinition(Declaration)},
        {"source_text", sourceText(Declaration->getSourceRange(), SM,
                                    Context.getLangOpts())},
        {"enum_ordinal", std::move(EnumOrdinal)},
        {"location", location(Location, SM)},
        {"range", sourceRange(Declaration->getSourceRange(), SM)}};
    if (const clang::RawComment *Comment =
            Context.getRawCommentForAnyRedecl(Declaration)) {
      if (Comment->isDocumentation()) {
        Record["documentation"] = Comment->getFormattedText(
            SM, Context.getDiagnostics());
        Record["documentation_location"] =
            location(Comment->getBeginLoc(), SM);
        Record["documentation_range"] =
            sourceRange(Comment->getSourceRange(), SM);
      }
    }
    Data.NonFunctionDeclarations.push_back(std::move(Record));
    return true;
  }

  bool VisitCallExpr(clang::CallExpr *Call) {
    clang::SourceManager &SM = Context.getSourceManager();
    clang::SourceLocation Begin = Call->getBeginLoc();
    if ((!ProjectionFile.empty() &&
         !isInPhysicalFile(Begin, SM, ProjectionFile)) ||
        (ProjectionFile.empty() && !SM.isWrittenInMainFile(Begin) &&
         !SM.isWrittenInMainFile(SM.getExpansionLoc(Begin))))
      return true;
    clang::SourceLocation Spelled = SM.getSpellingLoc(Begin);
    clang::SourceLocation Expanded = SM.getExpansionLoc(Begin);
    const std::string CallOrigin =
        Begin.isMacroID()
            ? (SM.isMacroArgExpansion(Begin) ? "macro_argument"
                                             : "macro_replacement")
            : CurrentCallerOrigin;
    const clang::FunctionDecl *Callee = Call->getDirectCallee();
    Array Arguments;
    for (unsigned Index = 0; Index < Call->getNumArgs(); ++Index) {
      const clang::Expr *Argument = Call->getArg(Index);
      Arguments.push_back(Object{
          {"index", static_cast<int64_t>(Index)},
          {"source_text", sourceText(Argument->getSourceRange(), SM,
                                      Context.getLangOpts())},
          {"range", sourceRange(Argument->getSourceRange(), SM)},
          {"location", location(Argument->getExprLoc(), SM)}});
    }
    std::string SpellingPath = SM.getFilename(SM.getFileLoc(Spelled)).str();
    int64_t SpellingOffset = static_cast<int64_t>(SM.getFileOffset(SM.getFileLoc(Spelled)));
    std::string ExpansionPath = SM.getFilename(SM.getFileLoc(Expanded)).str();
    int64_t ExpansionOffset = static_cast<int64_t>(SM.getFileOffset(SM.getFileLoc(Expanded)));
    Object CalleeRecord;
    if (Callee) {
      CalleeRecord["usr"] = semanticUSR(Callee);
      CalleeRecord["name"] = Callee->getNameAsString();
      CalleeRecord["qualified_name"] = Callee->getQualifiedNameAsString();
      CalleeRecord["signature"] = functionSignature(Callee);
      CalleeRecord["signature_kind"] = "derived_display_only";
      CalleeRecord["function_type"] = functionType(Callee);
      CalleeRecord["has_prototype"] = Callee->hasPrototype();
      CalleeRecord["is_variadic"] = Callee->isVariadic();
      CalleeRecord["decl_kind"] = declarationDeclKind(Callee);
      CalleeRecord["identity_kind"] = declarationKind(Callee);
    }
    Data.Calls.push_back(Object{
        {"caller_usr", CurrentCallerUSR.empty() ? Value(nullptr)
                                                : Value(CurrentCallerUSR)},
        {"caller_name", CurrentCallerName.empty() ? Value(nullptr)
                                                  : Value(CurrentCallerName)},
        {"caller_qualified_name",
         CurrentCallerQualifiedName.empty()
             ? Value(nullptr)
             : Value(CurrentCallerQualifiedName)},
        {"target_text", sourceText(Call->getCallee()->getSourceRange(), SM,
                                   Context.getLangOpts())},
        {"site_identity", SpellingPath + ":" + std::to_string(SpellingOffset)},
        {"expansion_identity", ExpansionPath + ":" + std::to_string(ExpansionOffset)},
        {"origin", CallOrigin},
        {"callee", Callee ? Value(std::move(CalleeRecord)) : Value(nullptr)},
        {"arguments", std::move(Arguments)},
        {"location", location(Begin, SM)},
        {"range", sourceRange(Call->getSourceRange(), SM)}});
    return true;
  }

private:
  bool withinRepository(const std::string &Path) const {
    std::error_code Error;
    std::filesystem::path Candidate = std::filesystem::weakly_canonical(Path, Error);
    if (Error)
      return false;
    std::filesystem::path Root = std::filesystem::weakly_canonical(RepositoryRoot, Error);
    if (Error)
      return false;
    auto CandidateIt = Candidate.begin();
    for (auto RootIt = Root.begin(); RootIt != Root.end(); ++RootIt, ++CandidateIt)
      if (CandidateIt == Candidate.end() || *CandidateIt != *RootIt)
        return false;
    return true;
  }

  clang::ASTContext &Context;
  FrontendData &Data;
  std::string MainFile;
  std::string RepositoryRoot;
  bool FullCapture;
  std::string ProjectionFile;
  std::string CurrentCallerUSR;
  std::string CurrentCallerName;
  std::string CurrentCallerQualifiedName;
  std::string CurrentCallerOrigin;
};

class Consumer final : public clang::ASTConsumer {
public:
  Consumer(clang::ASTContext &Context, FrontendData &Data,
           llvm::StringRef MainFile, llvm::StringRef RepositoryRoot,
           bool FullCapture, llvm::StringRef ProjectionFile)
      : Data(Data), Visitor(Context, Data, MainFile, RepositoryRoot,
                            FullCapture, ProjectionFile),
        ProjectionFile(ProjectionFile.str()) {}

  void HandleTranslationUnit(clang::ASTContext &Context) override {
    Visitor.TraverseDecl(Context.getTranslationUnitDecl());
    clang::SourceManager &SM = Context.getSourceManager();
    clang::FileID CommentFile = SM.getMainFileID();
    if (!ProjectionFile.empty()) {
      auto File = SM.getFileManager().getFileRef(ProjectionFile);
      if (!File) {
        llvm::consumeError(File.takeError());
        return;
      }
      CommentFile = SM.translateFile(*File);
    }
    const auto *Comments = Context.Comments.getCommentsInFile(CommentFile);
    if (!Comments)
      return;
    for (const auto &[Offset, Comment] : *Comments) {
      (void)Offset;
      if (!Comment || !Comment->isDocumentation())
        continue;
      Data.DocumentationComments.push_back(Object{
          {"text", Comment->getFormattedText(SM, Context.getDiagnostics())},
          {"location", location(Comment->getBeginLoc(), SM)},
          {"range", sourceRange(Comment->getSourceRange(), SM)}});
    }
  }

private:
  FrontendData &Data;
  FrontendVisitor Visitor;
  std::string ProjectionFile;
};

class Action final : public clang::ASTFrontendAction {
public:
  Action(FrontendData &Data, llvm::StringRef RepositoryRoot, bool FullCapture,
         llvm::StringRef ProjectionFile)
      : Data(Data), RepositoryRoot(RepositoryRoot.str()),
        FullCapture(FullCapture), ProjectionFile(ProjectionFile.str()) {}

  std::unique_ptr<clang::ASTConsumer>
  CreateASTConsumer(clang::CompilerInstance &CI, llvm::StringRef InFile) override {
    Data.TargetTriple = CI.getTarget().getTriple().str();
    Data.Sysroot = CI.getHeaderSearchOpts().Sysroot;
    clang::SourceManager &SM = CI.getSourceManager();
    clang::Preprocessor &PP = CI.getPreprocessor();
    const clang::HeaderSearch &HeaderSearch = PP.getHeaderSearchInfo();
    int64_t SearchOrder = 0;
    for (auto It = HeaderSearch.search_dir_begin();
         It != HeaderSearch.search_dir_end(); ++It, ++SearchOrder) {
      Data.SearchDirectories.push_back(Object{
          {"path", It->getName().str()},
          {"order", SearchOrder},
          {"is_framework", It->isFramework()},
          {"is_header_map", It->isHeaderMap()}});
    }
    PP.addPPCallbacks(std::make_unique<CallbackCollector>(
        Data, SM, CI.getLangOpts(), FullCapture, ProjectionFile));
    return std::make_unique<Consumer>(CI.getASTContext(), Data, InFile,
                                      RepositoryRoot, FullCapture,
                                      ProjectionFile);
  }

private:
  FrontendData &Data;
  std::string RepositoryRoot;
  bool FullCapture;
  std::string ProjectionFile;
};

class Factory final : public clang::tooling::FrontendActionFactory {
public:
  Factory(FrontendData &Data, llvm::StringRef RepositoryRoot, bool FullCapture,
          llvm::StringRef ProjectionFile)
      : Data(Data), RepositoryRoot(RepositoryRoot.str()),
        FullCapture(FullCapture), ProjectionFile(ProjectionFile.str()) {}

  std::unique_ptr<clang::FrontendAction> create() override {
    return std::make_unique<Action>(Data, RepositoryRoot, FullCapture,
                                    ProjectionFile);
  }

private:
  FrontendData &Data;
  std::string RepositoryRoot;
  bool FullCapture;
  std::string ProjectionFile;
};

class DiagnosticCollector final : public clang::DiagnosticConsumer {
public:
  explicit DiagnosticCollector(FrontendData &Data) : Data(Data) {}

  void HandleDiagnostic(clang::DiagnosticsEngine::Level Level,
                        const clang::Diagnostic &Info) override {
    clang::DiagnosticConsumer::HandleDiagnostic(Level, Info);
    llvm::SmallString<256> Message;
    Info.FormatDiagnostic(Message);
    std::string Severity = "note";
    if (Level == clang::DiagnosticsEngine::Warning)
      Severity = "warning";
    else if (Level == clang::DiagnosticsEngine::Error ||
             Level == clang::DiagnosticsEngine::Fatal)
      Severity = "error";
    Object Diagnostic{{"severity", Severity}, {"message", Message.str().str()}};
    if (Info.hasSourceManager())
      Diagnostic["location"] = location(Info.getLocation(), Info.getSourceManager());
    else
      Diagnostic["location"] = nullptr;
    Data.Diagnostics.push_back(std::move(Diagnostic));
  }

private:
  FrontendData &Data;
};

Value parseRequest(llvm::StringRef Input) {
  auto Parsed = llvm::json::parse(Input);
  if (!Parsed)
    return nullptr;
  return std::move(*Parsed);
}

} // namespace

int main() {
  std::string Input((std::istreambuf_iterator<char>(std::cin)),
                    std::istreambuf_iterator<char>());
  Value Parsed = parseRequest(Input);
  Object *Request = Parsed.getAsObject();
  if (!Request) {
    llvm::errs() << "input must be a JSON object\n";
    return 2;
  }
  auto File = Request->getString("file");
  auto Directory = Request->getString("directory");
  auto RepositoryRoot = Request->getString("repository_root");
  auto Arguments = Request->getArray("argv");
  auto RequestedCaptureMode = Request->getString("capture_mode");
  auto RequestedProjection = Request->getString("projection_file");
  if (!File || !Directory || !RepositoryRoot || !Arguments) {
    llvm::errs() << "input requires file, directory, repository_root, and argv\n";
    return 2;
  }
  std::vector<std::string> ClangArguments;
  for (const Value &Argument : *Arguments) {
    auto String = Argument.getAsString();
    if (!String) {
      llvm::errs() << "argv entries must be strings\n";
      return 2;
    }
    ClangArguments.push_back(String->str());
  }

  clang::tooling::FixedCompilationDatabase FixedDatabase(
      Directory->str(), ClangArguments);
  std::string CaptureMode = RequestedCaptureMode
                                ? RequestedCaptureMode->str()
                                : "full";
  if (CaptureMode != "source_relevant" && CaptureMode != "full") {
    llvm::errs() << "capture_mode must be source_relevant or full\n";
    return 2;
  }
  const std::string ProjectionFile =
      RequestedProjection ? RequestedProjection->str() : std::string();
  if (!ProjectionFile.empty() &&
      (!std::filesystem::path(ProjectionFile).is_absolute() ||
       !std::filesystem::is_regular_file(ProjectionFile))) {
    llvm::errs() << "projection_file must be an existing absolute file\n";
    return 2;
  }
  bool FullCapture = CaptureMode == "full";
  clang::tooling::ClangTool Tool(FixedDatabase, {File->str()});
  FrontendData Data;
  DiagnosticCollector Diagnostics(Data);
  Tool.setDiagnosticConsumer(&Diagnostics);
  Factory Actions(Data, *RepositoryRoot, FullCapture, ProjectionFile);
  int Result = Tool.run(&Actions);
  std::sort(Data.DependencyPaths.begin(), Data.DependencyPaths.end());
  Data.DependencyPaths.erase(
      std::unique(Data.DependencyPaths.begin(), Data.DependencyPaths.end()),
      Data.DependencyPaths.end());
  Array Dependencies;
  for (const std::string &Path : Data.DependencyPaths)
    Dependencies.push_back(Path);
  const std::string ProjectionMode = ProjectionFile.empty()
                                         ? CaptureMode
                                         : "header_projection";
  Object Output{{"schema_version", ProjectionFile.empty()
                                         ? "codira.clang-frontend-native/3"
                                         : "codira.clang-frontend-native/4"},
                {"translation_unit_file", File->str()},
                {"projection_file", ProjectionFile.empty()
                                         ? Value(nullptr)
                                         : Value(ProjectionFile)},
                {"declarations", std::move(Data.Declarations)},
                {"non_function_declarations",
                 std::move(Data.NonFunctionDeclarations)},
                {"calls", std::move(Data.Calls)},
                {"preprocessing", std::move(Data.Preprocessing)},
                {"documentation_comments",
                 std::move(Data.DocumentationComments)},
                {"includes", std::move(Data.Includes)},
                {"search_directories", std::move(Data.SearchDirectories)},
                {"diagnostics", std::move(Data.Diagnostics)},
                {"dependency_paths", std::move(Dependencies)},
                {"capture_mode", CaptureMode},
                {"capture_projection",
                 Object{{"mode", ProjectionMode},
                        {"translation_unit_file", File->str()},
                        {"requested_header_file", ProjectionFile.empty()
                                                        ? Value(nullptr)
                                                        : Value(ProjectionFile)},
                        {"omitted_header_function_declarations",
                         Data.OmittedHeaderFunctionDeclarations},
                        {"omitted_header_macro_definitions",
                         Data.OmittedHeaderMacroDefinitions},
                        {"omitted_header_preprocessing_events",
                         Data.OmittedHeaderPreprocessingEvents},
                        {"dependency_scope", "all_includes_and_files"}}},
                {"clang_version", CLANG_VERSION_STRING},
                {"target_triple", Data.TargetTriple},
                {"sysroot", Data.Sysroot},
                {"tool_return_code", Result}};
  llvm::outs() << llvm::formatv("{0}\n", Value(std::move(Output)));
  return 0;
}
