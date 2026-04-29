class PaperModel:
    def __init__(
        self,
        ID,
        Title,
        Abstract,
        Year,
        Best_oa_location,
        Referenced_works=None,
        Related_works=None,
        Cited_by_count=0,
        Authors=None,
        Institutions=None,
        Identifiers=None,
    ):
        self.ID = ID
        self.Title = Title
        self.Abstract = Abstract
        self.Year = Year
        self.Best_oa_location = Best_oa_location
        self.Referenced_works = list(Referenced_works or [])
        self.Related_works = list(Related_works or [])
        self.Cited_by_count = Cited_by_count
        self.Authors = list(Authors or [])
        self.Institutions = list(Institutions or [])
        self.Identifiers = list(Identifiers or [])
